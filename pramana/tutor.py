"""The grounded tutor.

One turn runs four steps:

1. **Understand** (small model). Rewrite the message as a standalone English search query,
   classify the intent, and read it as evidence about the student: did they just show they
   understood something, or reveal a confusion? If the tutor's last message ended with a
   check question, grade the reply.
2. **Retrieve** (local). Hybrid search plus re-ranking. If the student is weak on a
   prerequisite of what they asked about, that prerequisite's best passage is added, so the
   explanation can start where the student actually is.
3. **Answer** (tutor model). The reply comes back as segments, each naming the sources that
   support it, together with a verdict on whether the material covers the question at all.
4. **Enforce** (code, not the model). A segment with no valid source is removed from the
   grounded answer. If the material does not cover the question the tutor says so and points
   to the nearest material; outside knowledge is shown only when the student has allowed
   it, and then in a separate, labelled block.
"""
from __future__ import annotations

import re

from .cite import citation, study_links
from .config import settings
from .db import Database, now
from .learner import MASTERED, WEAK, Learner
from .llm import llm
from .retrieve import Hit, Index

# Below this cross-encoder logit nothing retrieved is about the question; refuse without a model call.
# Set from the evaluation's 53 test questions: the lowest top score of any in-material question
# was 2.3 and the highest of any other-subject question was -8.0 (see docs/evaluation.md).
NO_EVIDENCE = -3.0
LANGUAGES = {"en": "English", "hi": "Hindi (Devanagari script)", "hinglish": "Hinglish (Hindi in Latin script mixed with English technical terms)"}

UNDERSTAND_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "intent": {"type": "string", "enum": ["course_question", "answer_to_check", "study_advice", "smalltalk"]},
        "signals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "concept_id": {"type": "string"},
                    "signal": {"type": "string", "enum": ["understood", "confused", "misconception"]},
                    "note": {"type": "string"},
                },
                "required": ["concept_id", "signal", "note"],
            },
        },
        "check_result": {"type": "string", "enum": ["correct", "partial", "incorrect", "none"]},
    },
    "required": ["query", "intent", "signals", "check_result"],
}

UNDERSTAND_PROMPT = """You are the front desk of a course tutor. Read the student's new message in context.

Course concepts (id: name):
{concepts}

Recent conversation:
{history}
{pending}
Student's new message: {message}

Return:
- "query": the student's question rewritten in English as a standalone search query for the course material (resolve "it", "that", "the second one" from the conversation). If the message is an answer to the tutor's check question, use the check question itself.
- "intent": course_question (asks about subject matter), answer_to_check (answers the tutor's pending check question), study_advice (asks what to study, how they are doing, or for a plan), smalltalk (greeting, thanks, anything else).
- "signals": what this message reveals about the student's own understanding, if anything. Use "misconception" when they state something false as if true, "confused" when they say or show they do not follow, "understood" when they correctly explain or apply an idea. Only for concepts in the list; usually empty for a plain question. "note" is a short phrase describing what you saw.
- "check_result": if there is a pending check question and this message answers it, grade it against the expected answer: correct, partial or incorrect. Otherwise none.
"""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "coverage": {"type": "string", "enum": ["covered", "partial", "not_covered"]},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "sources": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "sources"],
            },
        },
        "missing": {"type": "string"},
        "outside": {"type": "string"},
        "check_question": {"type": "string"},
        "check_answer": {"type": "string"},
        "check_concept": {"type": "string"},
    },
    "required": ["coverage", "segments", "missing", "outside", "check_question", "check_answer", "check_concept"],
}

ANSWER_PROMPT = """You are a tutor for one specific course. You teach strictly from the course material given below, and you say so when it does not cover something.

Grounding rules:
- Write the answer as "segments" of one to three sentences. Each segment lists in "sources" the ids (S1, S2, ...) of the excerpts that state what the segment says. Never cite an excerpt that does not say it. Never write a segment you cannot source.
- "coverage": covered if the excerpts answer the question; partial if they answer only part of it; not_covered if they do not answer it. Being on a related subject is not enough: the excerpts must contain the answer.
- When coverage is partial, answer the part that is covered and say in "missing" what the material does not address. When not_covered, leave "segments" empty and say in "missing" what was asked that the material lacks.
- {outside_rule}
- Use the excerpts' own notation. Write maths as LaTeX between $...$. If an excerpt is a figure or a board reading, you may refer the student to it ("the free-body diagram shows...").

Teaching rules, fitted to this student:
{student}
- Be direct and concrete. No preamble, no praise, no summary of what you are about to do.
- Answer in {language}. Keep symbols, units and LaTeX unchanged.
- {check_rule}

{check_context}Course material:
{material}

Student's question: {question}
"""


def _history_block(history: list[dict]) -> str:
    if not history:
        return "(none)"
    return "\n".join(f"{m['role'].title()}: {m['content'][:500]}" for m in history[-4:])


def _student_block(learner: Learner, concept_ids: list[str]) -> tuple[str, list[str]]:
    """Guidance lines for the answer prompt, and the weak prerequisites worth recapping."""
    state = learner.state()
    lines, gaps = [], []
    for concept_id in concept_ids[:3]:
        s = state[concept_id]
        name = learner.concepts[concept_id]["name"]
        if s.n_obs == 0:
            lines.append(f"- No evidence yet on \"{name}\": explain from the definition and include one concrete example from the material.")
        elif s.current >= MASTERED:
            lines.append(f"- The student has mastered \"{name}\" ({s.current:.0%}): be brief, skip the basics, and connect it to what comes next.")
        elif s.current < WEAK:
            lines.append(f"- The student is weak on \"{name}\" ({s.current:.0%}): go step by step in plain language, define each symbol, and work one example from the material.")
        else:
            lines.append(f"- The student is developing on \"{name}\" ({s.current:.0%}): explain the key step and one common pitfall.")
        blocker = learner.weakest_prerequisite(concept_id, state)
        if blocker and blocker not in gaps:
            gaps.append(blocker)
            lines.append(f"- Their prerequisite \"{learner.concepts[blocker]['name']}\" is not secure ({state[blocker].current:.0%}): begin with a one- or two-sentence recap of it (cite the excerpt marked PREREQUISITE) before answering.")
    recent = learner.db.all(
        "SELECT detail FROM evidence WHERE student_id = ? AND correct < 1 ORDER BY id DESC LIMIT 20", [learner.student_id])
    seen = []
    for row in recent:
        label = (row["detail"].get("misconception") or row["detail"].get("note") or "").strip()
        if label and label not in seen:
            seen.append(label)
    if seen:
        lines.append("- Mistaken beliefs this student has shown recently; correct them explicitly if the question touches them: " + "; ".join(seen[:3]) + ".")
    return "\n".join(lines) or "- No history for this student yet: assume a beginner.", gaps


def _material(hits: list[Hit], extra: list[tuple[dict, str]], index: Index) -> tuple[str, list[dict]]:
    """Numbered excerpts for the prompt and the units behind the numbers."""
    units, blocks = [], []
    for hit in hits:
        units.append(hit.unit)
        source = index.sources[hit.unit["source_id"]]
        blocks.append(f"[S{len(units)}] {source['kind']} — {hit.unit['section'] or source['title']}\n{hit.context[:1600]}")
    for unit, tag in extra:
        if unit["id"] in {u["id"] for u in units}:
            continue
        units.append(unit)
        source = index.sources[unit["source_id"]]
        blocks.append(f"[S{len(units)}] {tag} {source['kind']} — {unit['section'] or source['title']}\n{index.context_for(unit)[:1200]}")
    return "\n\n".join(blocks), units


def _concepts_of(index: Index, hits: list[Hit]) -> list[str]:
    """Concepts the retrieved material is about, most supported first."""
    votes: dict[str, float] = {}
    for rank, hit in enumerate(hits[:4]):
        for concept_id in index.unit_concepts.get(hit.unit["id"], [])[:1]:
            votes[concept_id] = votes.get(concept_id, 0.0) + 1.0 / (1 + rank)
    return sorted(votes, key=lambda c: -votes[c])


def _advice(db: Database, course_id: str, learner: Learner) -> dict:
    """'What should I study?' is answered from the learner model, not by a language model."""
    snapshot = learner.snapshot()
    seen = [c for c in snapshot if c["n_obs"] > 0]
    if not seen:
        text = "I have no evidence about you yet. Take the 10-question diagnostic in Practice and I can tell you exactly where to start."
        return {"text": text, "links": []}
    weak = sorted((c for c in seen if c["mastery"] < MASTERED), key=lambda c: c["mastery"])[:3]
    if not weak:
        return {"text": "Everything you have been assessed on is at mastery. Try the concepts you have not met yet, or a mock exam.", "links": []}
    lines, links = [], []
    for concept in weak:
        target = concept["blocked_by"] or concept["concept_id"]
        target_name = learner.concepts[target]["name"]
        if concept["blocked_by"]:
            lines.append(f"**{concept['name']}** is at {concept['mastery']:.0%}, and it rests on **{target_name}**, which is not secure yet. Start there.")
        else:
            lines.append(f"**{concept['name']}** is at {concept['mastery']:.0%}. Review it, then take a short quiz on it.")
        links.extend(study_links(db, course_id, target, limit=2))
    return {"text": "\n\n".join(lines), "links": links}


def respond(
    db: Database,
    index: Index,
    course_id: str,
    student_id: str,
    message: str,
    language: str = "en",
    allow_outside: bool = False,
    personalise: bool = True,
    k: int = 6,
    record: bool = True,
    understand: bool = True,
    namespace: str = "tutor-answer",
) -> dict:
    """One tutor turn. Returns the reply with its citations and what it taught the learner model."""
    learner = Learner(db, student_id)
    history = db.all("SELECT * FROM messages WHERE student_id = ? ORDER BY id DESC LIMIT 6", [student_id])[::-1] if record else []
    pending = history[-1]["meta"].get("check") if history and history[-1]["role"] == "tutor" else None

    # 1. understand
    concept_list = "\n".join(f"{c['id']}: {c['name']}" for c in learner.concepts.values())
    pending_block = (
        f"\nThe tutor's last message ended with this check question: {pending['question']}\nExpected answer: {pending['answer']}\n"
        if pending else ""
    )
    if understand:
        understood = llm().chat(
            [{"role": "user", "content": UNDERSTAND_PROMPT.format(
                concepts=concept_list, history=_history_block(history), pending=pending_block, message=message)}],
            models=settings.bulk_models, namespace="tutor-understand", schema=UNDERSTAND_SCHEMA,
        ).json()
    else:  # the evaluation asks standalone questions and measures retrieval and answering only
        understood = {"query": message, "intent": "course_question", "signals": [], "check_result": "none"}
    query = understood.get("query") or message
    intent = understood.get("intent", "course_question")

    updates = []
    if personalise:
        if pending and understood.get("check_result") in ("correct", "partial", "incorrect") and pending.get("concept_id") in learner.concepts:
            score = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}[understood["check_result"]]
            before, after = learner.observe(pending["concept_id"], score, "short", 2, source="chat", weight=0.8,
                                            detail={"note": f"check question answered: {understood['check_result']}"})
            updates.append({"concept_id": pending["concept_id"], "name": learner.concepts[pending["concept_id"]]["name"],
                            "before": round(before, 3), "after": round(after, 3), "why": f"answered the check question ({understood['check_result']})"})
        for signal in understood.get("signals", []):
            if signal.get("concept_id") in learner.concepts:
                score = {"understood": 1.0, "confused": 0.3, "misconception": 0.0}[signal["signal"]]
                detail = {"note": signal.get("note", "")}
                if signal["signal"] == "misconception":
                    detail["misconception"] = signal.get("note", "")
                before, after = learner.observe(signal["concept_id"], score, "chat", 2, source="chat", weight=0.35, detail=detail)
                updates.append({"concept_id": signal["concept_id"], "name": learner.concepts[signal["concept_id"]]["name"],
                                "before": round(before, 3), "after": round(after, 3), "why": f"{signal['signal']}: {signal.get('note', '')}"})

    reply: dict = {
        "query": query, "intent": intent, "coverage": "covered", "segments": [], "citations": [], "outside": "",
        "missing": "", "refused": False, "related": [], "check": None, "learner_updates": updates, "retrieval": [],
    }

    if intent == "smalltalk":
        reply["segments"] = [{"text": "Ask me anything about the course material, and I will answer with the exact page, slide or moment in the lecture it comes from.", "citations": []}]
        reply["coverage"] = "not_applicable"
    elif intent == "study_advice":
        advice = _advice(db, course_id, learner)
        reply["segments"] = [{"text": advice["text"], "citations": []}]
        reply["related"] = advice["links"]
        reply["coverage"] = "not_applicable"
    else:
        # 2. retrieve
        hits = index.search(query, k=k)
        reply["retrieval"] = [{"unit_id": h.unit["id"], "score": round(h.score, 3)} for h in hits]
        concept_ids = _concepts_of(index, hits)
        student_block, gaps = _student_block(learner, concept_ids) if personalise else ("- No information about the student: give a clear, complete explanation.", [])
        extra = []
        for gap in gaps[:1]:
            rows = db.all(
                "SELECT u.* FROM units u JOIN unit_concepts uc ON uc.unit_id = u.id WHERE uc.concept_id = ? AND u.kind IN ('text', 'slide') "
                "ORDER BY uc.weight DESC, u.ord LIMIT 1", [gap])
            extra.extend((row, "PREREQUISITE") for row in rows)

        if not hits or hits[0].score < NO_EVIDENCE:
            verdict = {"coverage": "not_covered", "segments": [], "missing": "", "outside": "", "check_question": "", "check_answer": "", "check_concept": ""}
            units, model = [h.unit for h in hits], "retrieval-gate"
            if allow_outside:
                # The student asked for it: a short answer from general knowledge, shown under its own label.
                outside = llm().chat(
                    [{"role": "user", "content": f"Answer briefly (at most four sentences), in {LANGUAGES.get(language, 'English')}. Write maths as LaTeX between $...$.\n\nQuestion: {query}"}],
                    models=settings.tutor_models, namespace="tutor-outside", temperature=0.2,
                )
                verdict["outside"], model = outside.text.strip(), outside.model
        else:
            # 3. answer
            material, units = _material(hits, extra, index)
            check_context = ""
            if pending and intent == "answer_to_check":
                check_context = (f"The student is answering your check question: \"{pending['question']}\". Expected: {pending['answer']}. "
                                 f"Their answer was graded {understood.get('check_result')}. Tell them so, then explain from the material.\n\n")
            result = llm().chat(
                [{"role": "user", "content": ANSWER_PROMPT.format(
                    outside_rule=("\"outside\": if coverage is partial or not_covered, you may add a short answer from general knowledge here. It will be shown under the label \"Not from your course material\". Leave empty when coverage is covered."
                                  if allow_outside else "\"outside\": leave empty. Do not use knowledge from outside the excerpts anywhere."),
                    student=student_block, language=LANGUAGES.get(language, "English"),
                    check_rule=("End by setting \"check_question\" to one short question that makes the student use the idea you just explained (a small what-if, a quick calculation, or \"which of these...\"); it must not simply repeat their own question back. Set \"check_answer\" to its expected answer, and \"check_concept\" to the most relevant concept id from: " + ", ".join(concept_ids[:3]) + ". Leave all three empty if coverage is not_covered."
                                if concept_ids else "Leave the three check fields empty."),
                    check_context=check_context, material=material, question=query if language == "en" else f"{query} (original: {message})")}],
                models=settings.tutor_models, namespace=namespace, schema=ANSWER_SCHEMA, temperature=0.2,
            )
            verdict, model = result.json(), result.model

        # 4. enforce
        numbered: dict[str, int] = {}
        citations: list[dict] = []
        segments = []
        dropped = 0
        for segment in verdict.get("segments", []):
            text = segment.get("text", "").strip()
            valid = []
            for token in segment.get("sources", []):
                match = re.fullmatch(r"S(\d+)", token.strip())
                if match and 1 <= int(match.group(1)) <= len(units):
                    valid.append(units[int(match.group(1)) - 1])
            if not text:
                continue
            if not valid:
                dropped += 1
                continue
            refs = []
            for unit in valid:
                if unit["id"] not in numbered:
                    numbered[unit["id"]] = len(citations) + 1
                    citations.append({"n": numbered[unit["id"]], **citation(course_id, unit, index.sources[unit["source_id"]], text)})
                refs.append(numbered[unit["id"]])
            segments.append({"text": text, "citations": refs})
        coverage = verdict.get("coverage", "covered")
        if not segments:
            coverage = "not_covered"
        reply.update({
            "coverage": coverage, "segments": segments, "citations": citations, "missing": verdict.get("missing", "").strip(),
            "outside": verdict.get("outside", "").strip() if allow_outside and coverage != "covered" else "",
            "refused": coverage == "not_covered", "unsourced_segments_removed": dropped, "model": model,
            "contexts": [index.context_for(u) for u in units], "context_unit_ids": [u["id"] for u in units],
        })
        if coverage == "not_covered":
            # Point to the nearest material instead of answering.
            reply["related"] = [citation(course_id, h.unit, index.sources[h.unit["source_id"]]) for h in hits[:3] if h.score > -3.0]
        elif verdict.get("check_question") and verdict.get("check_concept") in learner.concepts:
            reply["check"] = {"question": verdict["check_question"].strip(), "answer": verdict.get("check_answer", "").strip(),
                              "concept_id": verdict["check_concept"]}

    if record:
        db.insert("messages", {"student_id": student_id, "ts": now(), "role": "student", "content": message, "meta": {"language": language}})
        text = " ".join(s["text"] for s in reply["segments"]) or reply["missing"] or "This is not covered in your course material."
        if reply["check"]:
            text += f"\n\nCheck: {reply['check']['question']}"
        public = {k: v for k, v in reply.items() if k not in ("contexts",)}
        reply["message_id"] = db.insert("messages", {"student_id": student_id, "ts": now(), "role": "tutor", "content": text,
                                                     "meta": {"check": reply["check"], "reply": public}})
    return reply
