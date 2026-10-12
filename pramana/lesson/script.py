"""Writes the storyboard of a lesson: which of the course's sources to show, in what order, and
what the narrator says over each.

The grounding rule is the tutor's, applied to film. A scene exists only if it names one of the
sources it was given; the words lit on a page must be found in that source; the stretch of
lecture played in the lecturer's own voice must be found in the transcript. A scene that fails
is dropped by code, and a lesson with too few scenes left is not made.
"""
from __future__ import annotations

import re

from ..cite import citation, clock, place
from ..config import settings
from ..db import Database, new_id, now
from ..learner import Learner
from ..llm import llm
from ..retrieve import Index
from . import build

VERSION = "lesson-v1"
QUOTA = {"text": 3, "slide": 2, "figure": 1, "transcript": 1, "frame": 1}     # how many sources of each kind are offered
KIND_LABEL = {"text": "textbook passage", "figure": "textbook figure", "slide": "slide", "transcript": "lecture, what is said", "frame": "lecture, what is on the board"}
ADVICE = {
    "unknown": "nothing is known about them yet, so start from the plainest statement and give each scene one idea.",
    "weak": "they are struggling with this concept, so start from the plainest statement, go slowly, and give each scene one idea.",
    "developing": "they half know this, so state the rule once, then spend the scenes on how it is used and where people slip.",
    "mastered": "they have mostly mastered this, so be brisk, and spend the scenes on the subtle points and what follows from the rule.",
}

PROMPT = """You are writing the narration of a short lesson film for one student. The film can show only the student's own course material, listed below as numbered sources: each scene puts ONE source on screen while a narrator speaks.

Concept: {name}. {description}
The student: {advice}{prerequisite}{misconception}

Sources:
{sources}

Write 4 to 6 scenes, as JSON.
- "source": the source on screen, for example "S2". Use each source at most once, and different kinds of source where there are any.
- "narration": what the narrator says over it: one or two short spoken sentences, 40 words at most. Say only what that source itself states or shows. No outside facts, no greetings, no "in this video". It will be read aloud: plain words, no symbols, no LaTeX, no markdown, and formulas said in words ("mu s times the normal force").
- "focus": for a textbook passage, copy from the source, word for word, the 5 to 14 consecutive plain words (no formulas) that the narration rests on; they are lit on the page. For a "listen" scene, copy word for word the 10 to 30 consecutive words of the lecture that the student should hear. Otherwise "".
- "mode": "listen" plays that stretch of the lecture in the lecturer's own voice instead of the narrator; it is allowed only on a source marked "lecture, what is said", and its narration must be "". Every other scene is "explain". If the sources include a "lecture, what is said" source, exactly one scene must be a "listen" scene: a lesson should let the student hear the lecturer once.
Order the scenes so that understanding builds: what it is, the rule, a picture of it, how the lecturer puts it, what follows from it."""

SCHEMA = {
    "type": "object",
    "properties": {"scenes": {"type": "array", "items": {
        "type": "object",
        "properties": {"source": {"type": "string"}, "mode": {"type": "string", "enum": ["explain", "listen"]},
                       "narration": {"type": "string"}, "focus": {"type": "string"}},
        "required": ["source", "mode", "narration", "focus"]}}},
    "required": ["scenes"],
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


def _source_line(n: int, unit: dict, prerequisite: bool) -> str:
    text = " ".join(re.sub(r"^### ", "", unit["text"], flags=re.M).split())[:1300]
    note = ", from the prerequisite" if prerequisite else ""
    return f"[S{n}] ({KIND_LABEL[unit['kind']]}, {place(unit)}{note})\n{text}"


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
    shaky = learner.weakest_prerequisite(concept_id, state)
    first = []
    if shaky:
        first = [u for u in material(db, index, learner.concepts[shaky]) if u["kind"] == "text"][:1]
    sources = first + [u for u in units if u not in first]
    if len(units) < 3:
        raise NotEnoughMaterial(f"the course has too little on “{concept['name']}” to cut a lesson from")
    seen = db.all("SELECT detail FROM evidence WHERE student_id = ? AND concept_id = ? ORDER BY ts DESC LIMIT 12", [student_id, concept_id])
    slips = list(dict.fromkeys(e["detail"]["misconception"] for e in seen if e["detail"].get("misconception")))[:2]
    prompt = PROMPT.format(
        name=concept["name"], description=concept["description"] or "", advice=ADVICE[level],
        prerequisite=f" Their grasp of the prerequisite “{learner.concepts[shaky]['name']}” is shaky: open with source S1, which is from that prerequisite, and recall it in one sentence." if first else "",
        misconception=(" In practice they have shown this mistaken belief: " + "; ".join(slips) + ". If a source speaks to it, let a scene do so.") if slips else "",
        sources="\n\n".join(_source_line(n, u, bool(first) and n == 1) for n, u in enumerate(sources, 1)),
    )
    result = llm().chat([{"role": "user", "content": prompt}], models=settings.tutor_models, namespace="lesson-script", schema=SCHEMA,
                        temperature=0.3, salt=f"{VERSION}:{concept_id}:{level}")
    scenes, dropped = _grounded(db, course_id, result.json().get("scenes", []), sources)
    if len(scenes) < 3:
        raise NotEnoughMaterial(f"only {len(scenes)} scenes of the draft could be tied to a source; a lesson needs three")

    # Number the sources in order of appearance and attach what the viewer opens when it clicks one.
    numbers: dict[str, int] = {}
    for scene in scenes:
        unit = index.by_id[scene["unit_id"]]
        source = db.one("SELECT * FROM sources WHERE id = ?", [unit["source_id"]])
        scene["n"] = numbers.setdefault(unit["id"], len(numbers) + 1)
        scene["citation"] = citation(course_id, unit, source, scene.get("narration") or scene.get("focus", ""))
        if scene["kind"] == "listen":
            scene["citation"]["place"] = clock(scene["t0"])
            scene["citation"]["locator"] = {**unit["locator"], "t_start": scene["t0"]}
    kinds = sorted({s["citation"]["source_kind"] for s in scenes})
    questions = db.one("SELECT COUNT(*) AS n FROM questions WHERE concept_id = ? AND status = 'verified'", [concept_id])["n"]
    title = {"kind": "title", "narration": f"{concept['name']}. A lesson cut from your own course.", "rule": 1, "lines": [
        ["A LESSON CUT FROM YOUR COURSE", "mono", 24, "cite"], [concept["name"], "serif", 78 if len(concept["name"]) < 30 else 60, "chalk"],
        [f"for {student['name']} · because {why}", "sans", 29, "dim"],
        [f"{len(numbers)} sources: " + ", ".join({"textbook": "the textbook", "slides": "the slides", "video": "the lectures"}[k] for k in kinds), "sans", 25, "dim"]]}
    credits = [f"{n}   {_credit(db, index.by_id[unit_id])}" for unit_id, n in numbers.items()]
    ending = {"kind": "end", "rule": 1, "narration": f"Now check yourself. {questions} checked questions on this are waiting in Practice." if questions else "That is the lesson. Every scene is in your course, at the place shown.",
              "lines": [["NOW CHECK YOURSELF" if questions else "EVERY SCENE IS IN YOUR COURSE", "mono", 24, "cite"],
                        [f"{questions} checked questions on this are waiting in Practice." if questions else "Open any source to read on from where the lesson stopped.", "serif", 46, "chalk"]]
                       + [[line, "sans", 22, "dim"] for line in credits]}
    return {
        "id": new_id("les"), "version": VERSION, "course": course_id, "student_id": student_id, "student": student["name"],
        "concept_id": concept_id, "concept": concept["name"], "level": level, "why": why, "language": language,
        "starts_from": learner.concepts[shaky]["name"] if first else None, "model": result.model, "created": now(),
        "scenes": [title] + scenes + [ending], "dropped": dropped,
    }


def _credit(db: Database, unit: dict) -> str:
    source = db.one("SELECT title, licence FROM sources WHERE id = ?", [unit["source_id"]])
    return f"{source['title']} · {place(unit)}" + (f" · {source['licence']}" if source.get("licence") else "")


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
                scenes.append({**scene, "kind": "listen", "narration": "", "focus": focus, "t0": round(span[0], 2), "t1": round(span[1], 2)})
                used.add(unit["id"])
                continue
            dropped.append("the words to be heard were not found in the lecture")
            if not narration:
                continue
        if not narration:
            dropped.append("a scene had nothing to say")
            continue
        if len(narration.split()) > 60:
            narration = " ".join(narration.split()[:60]).rsplit(".", 1)[0] + "."
            scene["narration"] = narration
        if kind == "text" and focus and _says(unit["text"], focus):
            scene["focus"] = focus
        scene["kind"] = {"text": "read", "figure": "figure", "slide": "slide"}.get(kind, "board")
        scenes.append(scene)
        used.add(unit["id"])
    return scenes, dropped


def _says(text: str, quote: str) -> bool:
    """True when the quote is in the source, word for word, give or take case, spacing and formulas."""
    flat = lambda s: " ".join(re.sub(r"\$[^$]*\$|[^a-z0-9 ]", " ", s.lower()).split())     # noqa: E731
    return len(flat(quote)) > 12 and flat(quote) in flat(text)
