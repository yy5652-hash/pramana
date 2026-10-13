"""Lessons: how much of each drafted storyboard survives the grounding checks, whether what
survives is supported by the source it is spoken over, and whether a lesson finds the student's
own mistake.

For every concept of the course a storyboard is written for a new student. No film is cut:
the picture adds nothing to these numbers. Counted:

* lessons made, and concepts for which the course held too little;
* teaching scenes kept and scenes dropped by code (no valid source, a source used twice, words
  to be heard that the lecture does not contain);
* lessons that walk through a worked example from the textbook, and its steps (kept only in the
  textbook's order and with the solution among them);
* textbook scenes whose quoted words were found in the passage word for word (only those are lit);
* lessons that let the student hear the lecturer, that take up a mistake, that end on a recap
  and on a checked question;
* every spoken line that makes a claim, judged against what it must rest on by the citation
  judge, a different model from the one that wrote the script: a scene or a step against its
  source, the words about the mistake against the question bank's own record of it, a point of
  the recap against the source it names.

Then, without a model: for every concept a student answers one of its questions wrongly, and
the lesson must find that answer and take it up as the student's own.

    python -m evaluation.lessons --course mechanics
"""
from __future__ import annotations

import argparse
from collections import Counter

from pramana.assess import session
from pramana.config import settings
from pramana.db import Database, new_id, now, open_course
from pramana.lesson import script
from pramana.llm import llm
from pramana.retrieve import Index

from .common import mean_ci, write_result
from .grounding import JUDGE_PROMPT, JUDGE_SCHEMA

SHOWN = ("read", "figure", "slide", "board", "listen")


def claims(db: Database, index: Index, board: dict) -> list[tuple[str, str, str]]:
    """Every spoken line of a lesson that makes a claim: (which part, the line, what it must rest on)."""
    out = []
    for scene in board["scenes"]:
        kind = scene["kind"]
        if kind in SHOWN + ("example",) and scene.get("narration"):
            out.append(("example" if kind == "example" else "teaching", scene["narration"], index.context_for(index.by_id[scene["unit_id"]])[:1800]))
        elif kind == "mistake":
            card, question = scene["card"], db.one("SELECT explanation FROM questions WHERE id = ?", [scene["question_id"]])
            out.append(("mistake", scene["narration"], f"Question: {card['stem']}\nThe wrong answer: {card['wrong']}\nThe correct answer: {card['right']}\n"
                        f"What the mistake is: {card['why']}\nWhy the correct answer is right: {question['explanation']}"))
        elif kind == "recap":
            out += [("recap", point["text"], index.context_for(index.by_id[point["unit_id"]])[:1800]) for point in scene["points"]]
    return out


def judge(lines: list[tuple[str, str, str]], author: str) -> list[str]:
    """One verdict per line: is it supported by what it must rest on?"""
    if not lines:
        return []
    blocks = [f"Segment {n}: {line}\n   [excerpt] {excerpt}" for n, (_, line, excerpt) in enumerate(lines, 1)]
    result = llm().chat([{"role": "user", "content": JUDGE_PROMPT.format(segments="\n\n".join(blocks))}],
                        models=[m for m in settings.judge_models if m != author] or settings.judge_models,
                        namespace="eval-lesson-judge", schema=JUDGE_SCHEMA)
    verdicts = {v.get("segment"): v.get("supported", "unjudged") for v in result.json().get("segments", [])}
    return [verdicts.get(n, "unjudged") for n in range(1, len(lines) + 1)]


def forget(db: Database, student_id: str) -> None:
    for table in ("attempts", "assessments", "evidence", "mastery", "messages", "lessons"):
        db.run(f"DELETE FROM {table} WHERE student_id = ?", [student_id])
    db.run("DELETE FROM students WHERE id = ?", [student_id])


def own_mistakes(db: Database, course_id: str) -> dict:
    """For each concept, a student who has just answered one of its questions wrongly: does the lesson find that answer?"""
    found, missing = 0, []
    for concept in db.all("SELECT * FROM concepts ORDER BY ord"):
        student = {"id": new_id("eval"), "name": "a student who slipped", "created": now(), "profile": {"simulated": True}}
        db.insert("students", student)
        try:
            sitting = session.start(db, student["id"], "quiz", [concept["id"]], n=1, types=["mcq", "numeric"])
            question = sitting["question"] and db.one("SELECT * FROM questions WHERE id = ?", [sitting["question"]["id"]])
            if not question:
                missing.append(concept["name"])
                continue
            key = question["answer"]
            wrong = (key["option"] + 1) % max(len(question["options"] or [1]), 1) if question["type"] == "mcq" else str(key["value"] * 2 or 1)
            session.answer(db, course_id, sitting["assessment_id"], question["id"], wrong)
            slip = script.mistake(db, student["id"], concept["id"])
            if slip and slip["own"] and slip["question_id"] == question["id"]:
                found += 1
            else:
                missing.append(concept["name"])
        finally:
            forget(db, student["id"])
    return {"concepts": found + len(missing), "found": found, "not_found": missing}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--course", default="mechanics")
    parser.add_argument("--no-judge", action="store_true")
    args = parser.parse_args()
    db = open_course(args.course)
    index = Index(db)
    student = {"id": new_id("eval"), "name": "a new student", "created": now(), "profile": {"simulated": True}}
    db.insert("students", student)
    made, thin, dropped, models = [], [], Counter(), set()
    verdicts: dict[str, list[str]] = {}
    try:
        for concept in db.all("SELECT * FROM concepts ORDER BY ord"):
            try:
                board = script.write(db, index, args.course, student["id"], concept["id"])
            except script.NotEnoughMaterial as error:
                thin.append({"concept": concept["name"], "why": str(error)})
                continue
            scenes = board["scenes"]
            shown = [s for s in scenes if s["kind"] in SHOWN]
            steps = [s for s in scenes if s["kind"] == "example"]
            read = [s for s in shown + steps if s["kind"] in ("read", "example")]
            slip = next((s for s in scenes if s["kind"] == "mistake"), None)
            recap = next((s for s in scenes if s["kind"] == "recap"), None)
            words = sum(len(s.get("narration", "").split()) for s in scenes)
            heard = sum(s["t1"] - s["t0"] for s in scenes if s["kind"] == "listen")
            row = {"concept": concept["name"], "scenes": len(shown), "example_steps": len(steps), "dropped": len(board["dropped"]),
                   "kinds": dict(Counter(s["kind"] for s in shown)), "read": len(read), "read_with_quote": sum(1 for s in read if s["focus"]),
                   "hears_the_lecturer": any(s["kind"] == "listen" for s in shown),
                   "mistake": None if not slip else "own" if slip["own"] else "from the question bank",
                   "recap_points": len(recap["points"]) if recap else 0, "ends_on_a_question": any(s["kind"] == "check" for s in scenes),
                   "narration_words": words, "seconds_about": round(words / 2.6 + heard + 0.75 * len(scenes) + 7.0)}
            dropped.update(board["dropped"])
            models.add(board["model"])
            if not args.no_judge:
                lines = claims(db, index, board)
                row["support"] = judge(lines, board["model"])
                for (part, _, _), verdict in zip(lines, row["support"]):
                    if verdict in ("yes", "partly", "no"):
                        verdicts.setdefault(part, []).append(verdict)
            made.append(row)
            print(f"{concept['name']:46s} {row['scenes']} scenes, {row['example_steps']} example steps, mistake: {row['mistake']}, recap {row['recap_points']}, "
                  f"about {row['seconds_about']} s, {row['dropped']} dropped, {Counter(row.get('support', []))}", flush=True)
    finally:
        forget(db, student["id"])

    def support(found: list[str]) -> dict:
        return {"lines_judged": len(found),
                "fully_supported": round(sum(v == "yes" for v in found) / max(len(found), 1), 4),
                "partly_supported": round(sum(v == "partly" for v in found) / max(len(found), 1), 4),
                "unsupported": round(sum(v == "no" for v in found) / max(len(found), 1), 4)}

    summary = {
        "version": script.VERSION, "concepts": len(made) + len(thin), "lessons_made": len(made), "too_little_material": thin,
        "scenes_kept": sum(r["scenes"] for r in made), "scenes_dropped": sum(r["dropped"] for r in made), "dropped_because": dict(dropped),
        "scenes_per_lesson": mean_ci([float(r["scenes"]) for r in made]),
        "kinds": dict(sum((Counter(r["kinds"]) for r in made), Counter())),
        "lessons_with_a_worked_example": sum(r["example_steps"] > 0 for r in made), "example_steps": sum(r["example_steps"] for r in made),
        "textbook_scenes": sum(r["read"] for r in made), "textbook_scenes_with_verified_quote": sum(r["read_with_quote"] for r in made),
        "lessons_with_the_lecturers_voice": sum(r["hears_the_lecturer"] for r in made),
        "lessons_with_a_mistake": sum(r["mistake"] is not None for r in made),
        "lessons_with_a_recap": sum(r["recap_points"] > 0 for r in made), "recap_points": sum(r["recap_points"] for r in made),
        "lessons_ending_on_a_question": sum(r["ends_on_a_question"] for r in made),
        "narration_words_per_lesson": mean_ci([float(r["narration_words"]) for r in made]),
        "seconds_per_lesson_about": mean_ci([float(r["seconds_about"]) for r in made]),
        "narration_support": support([v for found in verdicts.values() for v in found]),
        "support_by_part": {part: support(found) for part, found in sorted(verdicts.items())},
        "own_mistake_found": own_mistakes(db, args.course),
        "models": {"script": sorted(models), "judge": [m for m in settings.judge_models][:1]},
        "per_concept": made,
    }
    write_result("lessons", summary)
    print({k: summary[k] for k in ("lessons_made", "scenes_kept", "scenes_dropped", "lessons_with_a_worked_example", "lessons_with_a_mistake", "lessons_with_a_recap",
                                   "lessons_ending_on_a_question", "seconds_per_lesson_about", "narration_support", "support_by_part", "own_mistake_found")})


if __name__ == "__main__":
    main()
