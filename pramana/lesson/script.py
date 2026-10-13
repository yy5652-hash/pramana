"""Writes the storyboard of a lesson: which of the course's sources to show, in what order, and
what the narrator says over each.

A lesson has an arc. It teaches the concept from the textbook, the slides and the lecture; it
walks through a worked example the textbook itself gives, one step at a time; it takes up a
mistake, the student's own if they have made one in practice on this concept; it gathers what
to remember; and it ends on a checked question the student has not seen.

The grounding rule is the tutor's, applied to film. A scene exists only if it names one of the
sources it was given; the words lit on a page must be found in that source; the stretch of
lecture played in the lecturer's own voice must be found in the transcript; the steps of the
example must follow the textbook's order; a point of the recap is written on the scene whose
source states it, and is shown only if that scene was kept. A scene that fails is dropped by
code, and a lesson with too few scenes left is not made.
"""
from __future__ import annotations

import re

from ..assess.select import SIMILAR, TARGET_SUCCESS, Selector
from ..cite import citation, clock, place
from ..config import settings
from ..db import Database, new_id, now
from ..learner import Learner, predict_correct
from ..llm import llm
from ..retrieve import Index
from . import build, typeset

VERSION = "lesson-v2"
QUOTA = {"text": 3, "slide": 2, "figure": 1, "transcript": 1, "frame": 1}     # how many sources of each kind are offered
KIND_LABEL = {"text": "textbook passage", "figure": "textbook figure", "slide": "slide", "transcript": "lecture, what is said", "frame": "lecture, what is on the board"}
ROLE_LABEL = {"problem": "the problem", "strategy": "the strategy", "solution": "the solution", "significance": "what the answer means"}
ADVICE = {
    "unknown": "nothing is known about them yet, so start from the plainest statement and give each scene one idea.",
    "weak": "they are struggling with this concept, so start from the plainest statement, go slowly, and give each scene one idea.",
    "developing": "they half know this, so state the rule once, then spend the scenes on how it is used and where people slip.",
    "mastered": "they have mostly mastered this, so be brisk, and spend the scenes on the subtle points and what follows from the rule.",
}

PROMPT = """You are writing the narration of a lesson film for one student. The film can show only the student's own course material, listed below as numbered sources: each scene puts ONE source on screen while a narrator speaks.

Concept: {name}. {description}
The student: {advice}{prerequisite}

Sources:
{sources}
{example}{mistake}
Write the lesson as JSON with three parts.

"scenes": 4 to 5 scenes that teach the concept from the sources S1, S2, and so on.
- "source": the source on screen, for example "S2". Use each source at most once, and different kinds of source where there are any.
- "narration": what the narrator says over it: one or two short spoken sentences, 40 words at most. Say only what that source itself states or shows. No outside facts, no greetings, no "in this video". It will be read aloud: plain words, no symbols, no LaTeX, no markdown, and formulas said in words ("mu s times the normal force").
- "focus": for a textbook passage, copy from the source, word for word, the 5 to 14 consecutive plain words (no formulas) that the narration rests on; they are lit on the page. For a "listen" scene, copy word for word the 10 to 30 consecutive words of the lecture that the student should hear. Otherwise "".
- "mode": "listen" plays that stretch of the lecture in the lecturer's own voice instead of the narrator; it is allowed only on a source marked "lecture, what is said", and its narration must be "". Every other scene is "explain". If the sources include a "lecture, what is said" source, exactly one scene must be a "listen" scene: a lesson should let the student hear the lecturer once.
- "keep": the lesson ends on three things to remember. On the three scenes or example steps that carry them, write the thing to remember: one plain spoken sentence of at most 16 words that this scene's own source states, about the concept itself, a statement a student can carry to the next problem and not the numbers of the example. On every other scene and step, "".
Order them so that understanding builds: what it is, the rule, a picture of it, how the lecturer puts it.

"example": {example_rule}

"mistake": {mistake_rule}"""

EXAMPLE_RULE = """one step for each of {labels}, in that order, to walk the student through the textbook's worked example. Each step has "source" (its label), "narration" (45 words at most, spoken, plain words, numbers and units said in words: for the problem, what is asked; for the strategy, the plan; for the solution, the decisive step and the result; for what the answer means, the point of it. Say only what that source states), "focus" (as for a textbook passage above, or "" where the source is mostly formulas) and "keep" (as above)."""
MISTAKE_RULE = """two or three short spoken sentences, 45 words at most, {address}: what the mistake is and what is right instead. Say only what is written in the block about the mistake. Plain words, no symbols."""

STEP = {"type": "object", "properties": {"source": {"type": "string"}, "narration": {"type": "string"}, "focus": {"type": "string"}, "keep": {"type": "string"}},
        "required": ["source", "narration", "focus", "keep"]}
SCHEMA = {
    "type": "object",
    "properties": {
        "scenes": {"type": "array", "items": {
            "type": "object",
            "properties": {"source": {"type": "string"}, "mode": {"type": "string", "enum": ["explain", "listen"]},
                           "narration": {"type": "string"}, "focus": {"type": "string"}, "keep": {"type": "string"}},
            "required": ["source", "mode", "narration", "focus", "keep"]}},
        "example": {"type": "array", "items": STEP},
        "mistake": {"type": "string"},
    },
    "required": ["scenes", "example", "mistake"],
}


class NotEnoughMaterial(ValueError):
    """The course does not hold enough on this concept to cut a lesson from."""


def next_concept(db: Database, student_id: str) -> tuple[str, str]:
    """The concept this student's next lesson should be on, and why."""
    from ..assess.select import concept_priority

    learner = Learner(db, student_id)
    state = learner.state()
    best = max(learner.concepts, key=lambda c: concept_priority(learner, state, c))
    s = state[best]
    if s.n_obs == 0:
        why = "nothing is known about it yet, and you are ready for it"
    elif s.p - s.current > 0.08:
        why = "you knew it, and it is fading"
    else:
        why = "it is your weakest concept among those you are ready for"
    return best, why


def material(db: Database, index: Index, concept: dict) -> list[dict]:
    """The sources a lesson on this concept may show: the units most about it, a few of each kind.

    The textbook, the slides and the lectures are searched separately. In one ranked list the
    textbook, which has many times more passages, would crowd the other two out.
    """
    query = f"{concept['name']}. {concept['description'] or ''}"
    picked, count = [], dict.fromkeys(QUOTA, 0)
    for source_kind in ("textbook", "slides", "video"):
        ids = {row["id"] for row in db.all("SELECT id FROM sources WHERE kind = ?", [source_kind])}
        if not ids:
            continue
        for hit in index.search(query, k=24, pool=40, source_ids=ids, concept_ids={concept["id"]}):
            unit = hit.unit
            kind = unit["kind"]
            opening = unit["text"].lstrip("# ").lower()
            if kind not in QUOTA or count[kind] >= QUOTA[kind] or len(unit["text"]) < 80:
                continue
            if kind == "text" and opening.startswith(("learning objectives", "check your understanding", "solution", "strategy", "significance")):
                continue
            if kind in ("text", "figure") and "rect" not in unit["locator"]:
                continue
            picked.append(unit)
            count[kind] += 1
    # One moment of one lecture: what is said there and what is on the board belong together.
    lecture = next((u for u in picked if u["kind"] in ("transcript", "frame")), None)
    if lecture:
        sibling = index.by_id.get(lecture["locator"].get("sibling", ""))
        picked = [u for u in picked if u["kind"] not in ("transcript", "frame")] + [lecture] + ([sibling] if sibling else [])
    order = {"text": 0, "slide": 1, "figure": 2, "transcript": 3, "frame": 4}
    return sorted(picked, key=lambda u: (order[u["kind"]], u["source_id"], u["ord"]))


def _opening(unit: dict) -> str:
    return unit["text"].lstrip("# ").lower()


def worked_example(db: Database, concept_id: str, exclude: set[str] = frozenset()) -> list[tuple[str, dict]]:
    """A worked example the textbook gives on this concept, as its parts in the book's order:
    the problem, the strategy, the solution, and what the answer means.

    The textbook prints each example in that fixed pattern, and ingestion kept the parts as
    separate passages. The example chosen is the one whose parts are tagged most strongly with
    the concept; the earliest wins a tie, which is usually the plainest one.
    """
    units = db.all("SELECT u.* FROM units u JOIN sources s ON s.id = u.source_id WHERE s.kind = 'textbook' AND u.kind = 'text' ORDER BY u.source_id, u.ord")
    weight = {row["unit_id"]: row["weight"] for row in db.all("SELECT unit_id, weight FROM unit_concepts WHERE concept_id = ?", [concept_id])}
    best, best_score = [], 0.0
    for i in range(1, len(units) - 1):
        if not _opening(units[i]).startswith("strategy") or not _opening(units[i + 1]).startswith("solution"):
            continue
        if units[i]["source_id"] != units[i + 1]["source_id"]:
            continue
        problem = next((units[j] for j in range(i - 1, max(i - 7, -1), -1) if re.match(r"example\s+\d", _opening(units[j]))), units[i - 1])
        if _opening(problem).startswith(("solution", "significance", "strategy", "check your understanding", "learning objectives")):
            problem = None
        parts = [("problem", problem), ("strategy", units[i]), ("solution", units[i + 1])]
        if i + 2 < len(units) and _opening(units[i + 2]).startswith("significance"):
            parts.append(("significance", units[i + 2]))
        parts = [(role, unit) for role, unit in parts if unit and "rect" in unit["locator"] and unit["id"] not in exclude and len(unit["text"]) >= 60]
        if "solution" not in {role for role, _ in parts} or len(parts) < 2:
            continue
        score = sum(weight.get(unit["id"], 0.0) for _, unit in parts)
        if score > best_score:
            best, best_score = parts, score
    return best


def _plain_answer(question: dict, response) -> str:
    """What the student answered, as they would recognise it."""
    answer = question["answer"]
    if isinstance(response, dict):
        response = response.get("value", response.get("option", ""))
    if question["type"] == "mcq":
        try:
            return (question["options"] or [])[int(response)]
        except (TypeError, ValueError, IndexError):
            return ""
    return _quantity(str(response).strip(), answer.get("unit", ""))


def _quantity(value, unit: str) -> str:
    """A number with its unit, set as a formula so that m/s^2 gets its exponent."""
    try:
        value = f"{float(value):.4g}"
    except (TypeError, ValueError):
        return f"{value} {unit}".strip()
    written = typeset.unit(unit)
    return f"${value}" + (f"\\ {written}$" if written and not written.startswith("^") else f"{written}$")


def mistake(db: Database, student_id: str, concept_id: str) -> dict | None:
    """A mistake for the lesson to take up: the student's own latest wrong answer on this concept,
    or, if they have made none, a wrong answer the question bank marks as a common one."""
    def packed(question: dict, wrong: str, right: str, why: str, own: bool) -> dict | None:
        unit_id = next((u for u in question["unit_ids"] or [] if db.one("SELECT id FROM units WHERE id = ?", [u])), None)
        if not wrong or not right or not unit_id:
            return None
        return {"own": own, "question_id": question["id"], "stem": question["stem"], "wrong": wrong, "right": right, "why": why.strip(),
                "explanation": question["explanation"] or "", "unit_id": unit_id}

    rows = db.all("SELECT a.response, a.feedback, q.* FROM attempts a JOIN questions q ON q.id = a.question_id "
                  "WHERE a.student_id = ? AND q.concept_id = ? AND a.score < 0.5 AND q.type IN ('mcq', 'numeric') ORDER BY a.ts DESC LIMIT 6", [student_id, concept_id])
    rows.sort(key=lambda r: not (r["feedback"] or {}).get("misconception"))          # a mistake with a name first
    for row in rows:
        feedback = row["feedback"] or {}
        right = (row["options"] or [""])[row["answer"]["option"]] if row["type"] == "mcq" else _quantity(row["answer"].get("value"), row["answer"].get("unit", ""))
        found = packed(row, _plain_answer(row, row["response"]), right, feedback.get("misconception", ""), True)
        if found:
            return found
    for question in db.all("SELECT * FROM questions WHERE concept_id = ? AND status = 'verified' AND type = 'mcq' ORDER BY difficulty, id", [concept_id]):
        slips = question["answer"].get("misconceptions") or []
        tempting = next((i for i, slip in enumerate(slips) if slip and i != question["answer"]["option"] and i < len(question["options"])), None)
        if tempting is not None:
            found = packed(question, question["options"][tempting], question["options"][question["answer"]["option"]], slips[tempting], False)
            if found:
                return found
    return None


def check_question(db: Database, student_id: str, concept_id: str, avoid: set[str] = frozenset()) -> dict | None:
    """A checked question to end on: one this student has not met, near the success rate practice
    aims for, and short enough to read on a screen. Multiple choice if there is one."""
    import numpy as np

    from .. import embed

    selector = Selector(db, student_id)
    seen, vectors = selector._seen()
    mastery = selector.learner.state()[concept_id].current

    def fresh(question: dict) -> bool:
        if question["id"] in seen or question["id"] in avoid:
            return False
        return vectors is None or not question["vec"] or float(np.max(vectors @ embed.from_blob(question["vec"]))) < SIMILAR

    def length(question: dict) -> int:
        return len(question["stem"]) + sum(len(option) for option in question["options"] or [])

    for kinds in (["mcq"], ["numeric"]):
        pool = [q for q in selector._bank([concept_id], kinds) if fresh(q) and length(q) <= 520]
        if pool:
            return min(pool, key=lambda q: (round(abs(predict_correct(mastery, q["type"], q["difficulty"]) - TARGET_SUCCESS), 1), length(q), q["id"]))
    return None


def _source_line(label: str, unit: dict, note: str) -> str:
    text = " ".join(re.sub(r"^### ", "", unit["text"], flags=re.M).split())[:1300]
    return f"[{label}] ({note}, {place(unit)})\n{text}"


def write(db: Database, index: Index, course_id: str, student_id: str, concept_id: str | None = None, language: str = "en") -> dict:
    """The storyboard of a lesson for this student. Raises NotEnoughMaterial when none can honestly be made."""
    student = db.one("SELECT * FROM students WHERE id = ?", [student_id])
    learner = Learner(db, student_id)
    state = learner.state()
    recommended, reason = next_concept(db, student_id)
    concept_id = concept_id or recommended
    why = reason if concept_id == recommended else "you asked for it"
    concept = db.one("SELECT * FROM concepts WHERE id = ?", [concept_id])
    if not concept:
        raise NotEnoughMaterial("unknown concept")
    level = state[concept_id].level
    units = material(db, index, concept)
    if len(units) < 3:
        raise NotEnoughMaterial(f"the course has too little on “{concept['name']}” to cut a lesson from")
    shaky = learner.weakest_prerequisite(concept_id, state)
    first = []
    if shaky:
        first = [u for u in material(db, index, learner.concepts[shaky]) if u["kind"] == "text"][:1]
    sources = first + [u for u in units if u not in first]
    example = worked_example(db, concept_id, exclude={u["id"] for u in sources})
    slip = mistake(db, student_id, concept_id)

    example_block = mistake_block = ""
    if example:
        example_block = "\nA worked example from the textbook, in the book's own order:\n" + "\n\n".join(
            _source_line(f"E{n}", unit, ROLE_LABEL[role]) for n, (role, unit) in enumerate(example, 1)) + "\n"
    if slip:
        opening = "In practice this student answered a question on this concept wrongly." if slip["own"] else "A mistake students often make on this concept, from the course's question bank."
        mistake_block = (f"\nThe mistake. {opening}\nQuestion: {slip['stem']}\n{'Their answer' if slip['own'] else 'The tempting wrong answer'}: {slip['wrong']}\n"
                         f"The correct answer: {slip['right']}\n" + (f"What the mistake is: {slip['why']}\n" if slip["why"] else "")
                         + f"Why the correct answer is right: {slip['explanation']}\n")
    prompt = PROMPT.format(
        name=concept["name"], description=concept["description"] or "", advice=ADVICE[level],
        prerequisite=f" Their grasp of the prerequisite “{learner.concepts[shaky]['name']}” is shaky: open with source S1, which is from that prerequisite, and recall it in one sentence." if first else "",
        sources="\n\n".join(_source_line(f"S{n}", u, KIND_LABEL[u["kind"]] + (", from the prerequisite" if first and n == 1 else "")) for n, u in enumerate(sources, 1)),
        example=example_block, mistake=mistake_block,
        example_rule=EXAMPLE_RULE.format(labels=", ".join(f"E{n}" for n in range(1, len(example) + 1))) if example else "an empty list: no worked example was given.",
        mistake_rule=MISTAKE_RULE.format(address='addressed to the student as "you", who made it' if slip and slip["own"] else "about that mistake") if slip else 'an empty string: no mistake was given.',
    )
    result = llm().chat([{"role": "user", "content": prompt}], models=settings.tutor_models, namespace="lesson-script", schema=SCHEMA, temperature=0.3,
                        salt=f"{VERSION}:{concept_id}:{level}:{slip['question_id'] if slip else ''}:{'own' if slip and slip['own'] else 'bank'}")
    draft = result.json()
    scenes, dropped = _grounded(db, course_id, draft.get("scenes", []), sources)
    if len(scenes) < 3:
        raise NotEnoughMaterial(f"only {len(scenes)} scenes of the draft could be tied to a source; a lesson needs three")
    steps, lost = _steps(draft.get("example", []), example)
    dropped += lost

    # Number the sources in order of appearance and attach what the viewer opens when it clicks one.
    numbers: dict[str, int] = {}

    def cited(scene: dict, claim: str) -> dict:
        unit = index.by_id[scene["unit_id"]]
        source = db.one("SELECT * FROM sources WHERE id = ?", [unit["source_id"]])
        scene["n"] = numbers.setdefault(unit["id"], len(numbers) + 1)
        scene["citation"] = citation(course_id, unit, source, claim)
        return scene

    for scene in scenes:
        cited(scene, scene.get("narration") or scene.get("focus", ""))
        if scene["kind"] == "listen":
            unit = index.by_id[scene["unit_id"]]
            scene["citation"]["place"] = clock(scene["t0"])
            scene["citation"]["locator"] = {**unit["locator"], "t_start": scene["t0"]}
    for k, step in enumerate(steps, 1):
        cited(step, step["narration"]).update(step=k, steps=len(steps))

    extra: list[dict] = []
    said = " ".join(str(draft.get("mistake", "")).split())
    if slip:
        if not said or len(said.split()) > 70:
            said = f"Here is a mistake to avoid. {slip['why'][0].upper() + slip['why'][1:]}." if slip["why"] else ""
            if said:
                dropped.append("the words about the mistake were missing or too long, so the question bank's own were used")
        if said and slip["unit_id"] in index.by_id:
            extra.append(cited({"kind": "mistake", "own": slip["own"], "unit_id": slip["unit_id"], "question_id": slip["question_id"], "narration": said, "card": {
                "label": "FROM YOUR OWN PRACTICE" if slip["own"] else "A MISTAKE TO AVOID", "stem": slip["stem"],
                "wrong_label": "YOU ANSWERED" if slip["own"] else "TEMPTING", "wrong": slip["wrong"], "right": slip["right"], "why": slip["why"]}}, said))
    points = _points(scenes + steps)
    if len(points) >= 2:
        extra.append({"kind": "recap", "narration": "To keep. " + " ".join(p["text"] if p["text"][-1] in ".!?" else p["text"] + "." for p in points), "points": points})
    questions = db.one("SELECT COUNT(*) AS n FROM questions WHERE concept_id = ? AND status = 'verified'", [concept_id])["n"]
    closing = check_question(db, student_id, concept_id, avoid={slip["question_id"]} if slip else set())
    if closing:
        unit = closing["answer"].get("unit", "")
        extra.append({"kind": "check", "question_id": closing["id"], "narration": "Now try this one. Pause here, then answer it in Practice.", "card": {
            "label": f"TRY THIS ONE · DIFFICULTY {closing['difficulty']} OF 5", "stem": closing["stem"], "options": closing["options"] or [],
            "foot": (f"Give your answer in ${typeset.unit(unit)}$. " if typeset.unit(unit) and not closing["options"] else "")
                    + f"The answer is in Practice, with {questions} checked questions on this concept."}})

    kinds = sorted({s["citation"]["source_kind"] for s in scenes + steps})
    inside = ["the idea", "the rule"] + (["a worked example"] if steps else []) + ([("your own mistake" if slip["own"] else "a mistake to avoid")] if any(s["kind"] == "mistake" for s in extra) else []) \
        + (["what to keep"] if any(s["kind"] == "recap" for s in extra) else []) + (["one question"] if closing else [])
    title = {"kind": "title", "narration": f"{concept['name']}. A lesson cut from your own course.", "rule": 1, "lines": [
        ["A LESSON CUT FROM YOUR COURSE", "mono", 24, "cite"], [concept["name"], "serif", 78 if len(concept["name"]) < 30 else 60, "chalk"],
        [f"for {student['name']} · because {why}", "sans", 29, "dim"],
        [f"{len(numbers)} sources: " + ", ".join({"textbook": "the textbook", "slides": "the slides", "video": "the lectures"}[k] for k in kinds), "sans", 25, "dim"],
        ["  ·  ".join(inside), "sans", 22, "dim"]]}
    credits = [f"{n}   {_credit(db, index.by_id[unit_id])}" for unit_id, n in numbers.items()]
    ending = {"kind": "end", "rule": 1, "narration": ("" if closing else "That is the lesson. ") + "Every scene of it is in your course, at the place shown.",
              "lines": [["EVERY SCENE IS IN YOUR COURSE", "mono", 24, "cite"], ["Open any source to read on from where the lesson stopped.", "serif", 40, "chalk"]]}
    ending["lines"] += [[line, "sans", 20 if len(credits) > 7 else 22, "dim"] for line in credits]
    return {
        "id": new_id("les"), "version": VERSION, "course": course_id, "student_id": student_id, "student": student["name"],
        "concept_id": concept_id, "concept": concept["name"], "level": level, "why": why, "language": language,
        "starts_from": learner.concepts[shaky]["name"] if first else None, "model": result.model, "created": now(),
        "scenes": [title] + scenes + steps + extra + [ending], "dropped": dropped,
    }


def _credit(db: Database, unit: dict) -> str:
    source = db.one("SELECT title, licence FROM sources WHERE id = ?", [unit["source_id"]])
    return f"{source['title']} · {place(unit)}" + (f" · {source['licence']}" if source.get("licence") else "")


def _points(parts: list[dict]) -> list[dict]:
    """What to keep: the sentences the script wrote on the scenes and steps that survived, the first three.
    Each carries the citation number of the scene it was written on, so it rests on a source the film showed."""
    points = [{"text": part["keep"], "n": part["n"], "unit_id": part["unit_id"]} for part in parts if part.get("keep")][:3]
    for part in parts:
        part.pop("keep", None)
    return points


def _kept(draft: dict) -> str:
    """The thing to remember that a scene carries, if it carries one of a length that fits a card."""
    text = " ".join(str(draft.get("keep", "")).split())
    return text if 3 <= len(text.split()) <= 24 else ""


def _clip(narration: str, words: int) -> str:
    """A line kept to a length that can be spoken over one picture, cut at a sentence."""
    if len(narration.split()) <= words:
        return narration
    cut = " ".join(narration.split()[:words])
    return (cut.rsplit(".", 1)[0] if "." in cut else cut.rstrip(",;:")) + "."


def _grounded(db: Database, course_id: str, drafts: list[dict], sources: list[dict]) -> tuple[list[dict], list[str]]:
    """Keep the scenes that can be tied to a source; say why the others were dropped."""
    from ..ingest.video import transcribe

    scenes, dropped, used = [], [], set()
    for draft in drafts[:7]:
        match = re.fullmatch(r"\s*\[?S(\d+)\]?\s*", str(draft.get("source", "")))
        if not match or not 1 <= int(match.group(1)) <= len(sources):
            dropped.append("a scene named no valid source")
            continue
        unit = sources[int(match.group(1)) - 1]
        if unit["id"] in used:
            dropped.append(f"S{match.group(1)} was used twice")
            continue
        narration, focus, kind = " ".join(str(draft.get("narration", "")).split()), " ".join(str(draft.get("focus", "")).split()), unit["kind"]
        scene = {"unit_id": unit["id"], "narration": narration, "focus": ""}
        if draft.get("mode") == "listen" and kind == "transcript":
            source = db.one("SELECT * FROM sources WHERE id = ?", [unit["source_id"]])
            span = build.spoken_span(transcribe(build.raw_file(course_id, source)), unit["locator"]["t_start"], unit["locator"]["t_end"], focus)
            if span:
                scenes.append({**scene, "kind": "listen", "narration": "", "focus": focus, "t0": round(span[0], 2), "t1": round(span[1], 2), "keep": _kept(draft)})
                used.add(unit["id"])
                continue
            dropped.append("the words to be heard were not found in the lecture")
            if not narration:
                continue
        if not narration:
            dropped.append("a scene had nothing to say")
            continue
        scene["narration"] = _clip(narration, 60)
        scene["keep"] = _kept(draft)
        if kind == "text" and focus and _says(unit["text"], focus):
            scene["focus"] = focus
        scene["kind"] = {"text": "read", "figure": "figure", "slide": "slide"}.get(kind, "board")
        scenes.append(scene)
        used.add(unit["id"])
    return scenes, dropped


def _steps(drafts: list[dict], example: list[tuple[str, dict]]) -> tuple[list[dict], list[str]]:
    """The steps of the worked example that can be kept: each names a part of the example, the
    parts come in the textbook's order, and the solution is among them. Otherwise there is no example."""
    steps, dropped, last = [], [], 0
    for draft in drafts[:6]:
        match = re.fullmatch(r"\s*\[?E(\d+)\]?\s*", str(draft.get("source", "")))
        if not match or not 1 <= int(match.group(1)) <= len(example):
            dropped.append("a step of the example named no part of it")
            continue
        n = int(match.group(1))
        if n <= last:
            dropped.append(f"E{n} came out of the textbook's order")
            continue
        role, unit = example[n - 1]
        narration, focus = " ".join(str(draft.get("narration", "")).split()), " ".join(str(draft.get("focus", "")).split())
        if not narration:
            dropped.append("a step of the example had nothing to say")
            continue
        steps.append({"kind": "example", "role": role, "unit_id": unit["id"], "narration": _clip(narration, 70), "focus": focus if focus and _says(unit["text"], focus) else "",
                      "keep": _kept(draft)})
        last = n
    if steps and ("solution" not in {s["role"] for s in steps} or len(steps) < 2):
        return [], dropped + ["the worked example was left without its solution, so it was not shown"]
    return steps, dropped


def _says(text: str, quote: str) -> bool:
    """True when the quote is in the source, word for word, give or take case, spacing and formulas."""
    flat = lambda s: " ".join(re.sub(r"\$[^$]*\$|[^a-z0-9 ]", " ", s.lower()).split())     # noqa: E731
    return len(flat(quote)) > 12 and flat(quote) in flat(text)
