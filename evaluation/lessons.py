"""Lessons: how much of each drafted storyboard survives the grounding check, and whether the
narration that survives is supported by the source it is spoken over.

For every concept of the course a storyboard is written for a new student. No film is cut:
the picture adds nothing to these numbers. Counted:

* lessons made, and concepts for which the course held too little;
* scenes kept and scenes dropped by code (no valid source, a source used twice, words to be
  heard that the lecture does not contain);
* textbook scenes whose quoted words were found in the passage word for word (only those
  are lit on the page);
* lessons that let the student hear the lecturer;
* narration lines judged against their source by the citation judge, which is a different
  model from the one that wrote the script.

    python -m evaluation.lessons --course mechanics
"""
from __future__ import annotations

import argparse
from collections import Counter

from pramana.config import settings
from pramana.db import new_id, now, open_course
from pramana.lesson import script
from pramana.llm import llm
from pramana.retrieve import Index

from .common import mean_ci, write_result
from .grounding import JUDGE_PROMPT, JUDGE_SCHEMA


def judge(index: Index, board: dict) -> list[str]:
    """One verdict per narrated scene: is the line supported by the source it is spoken over?"""
    scenes = [s for s in board["scenes"] if s.get("unit_id") and s.get("narration")]
    if not scenes:
        return []
    blocks = [f"Segment {n}: {s['narration']}\n   [excerpt] {index.context_for(index.by_id[s['unit_id']])[:1800]}" for n, s in enumerate(scenes, 1)]
    result = llm().chat([{"role": "user", "content": JUDGE_PROMPT.format(segments="\n\n".join(blocks))}],
                        models=[m for m in settings.judge_models if m != board["model"]] or settings.judge_models,
                        namespace="eval-lesson-judge", schema=JUDGE_SCHEMA)
    verdicts = {v.get("segment"): v.get("supported", "unjudged") for v in result.json().get("segments", [])}
    return [verdicts.get(n, "unjudged") for n in range(1, len(scenes) + 1)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--course", default="mechanics")
    parser.add_argument("--no-judge", action="store_true")
    args = parser.parse_args()
    db = open_course(args.course)
    index = Index(db)
    student = {"id": new_id("eval"), "name": "a new student", "created": now(), "profile": {"simulated": True}}
    db.insert("students", student)
    made, thin, verdicts, dropped, models = [], [], [], Counter(), set()
    try:
        for concept in db.all("SELECT * FROM concepts ORDER BY ord"):
            try:
                board = script.write(db, index, args.course, student["id"], concept["id"])
            except script.NotEnoughMaterial as error:
                thin.append({"concept": concept["name"], "why": str(error)})
                continue
            scenes = [s for s in board["scenes"] if s.get("unit_id")]
            read = [s for s in scenes if s["kind"] == "read"]
            row = {"concept": concept["name"], "scenes": len(scenes), "dropped": len(board["dropped"]),
                   "kinds": dict(Counter(s["kind"] for s in scenes)), "read": len(read), "read_with_quote": sum(1 for s in read if s["focus"]),
                   "hears_the_lecturer": any(s["kind"] == "listen" for s in scenes),
                   "narration_words": sum(len(s["narration"].split()) for s in scenes)}
            dropped.update(board["dropped"])
            models.add(board["model"])
            if not args.no_judge:
                row["support"] = judge(index, board)
                verdicts += [v for v in row["support"] if v in ("yes", "partly", "no")]
            made.append(row)
            print(f"{concept['name']:48s} {row['scenes']} scenes, {row['dropped']} dropped, {row.get('support', '')}", flush=True)
    finally:
        db.run("DELETE FROM students WHERE id = ?", [student["id"]])
    kept, lost = sum(r["scenes"] for r in made), sum(r["dropped"] for r in made)
    summary = {
        "concepts": len(made) + len(thin), "lessons_made": len(made), "too_little_material": thin,
        "scenes_kept": kept, "scenes_dropped": lost, "dropped_because": dict(dropped),
        "scenes_per_lesson": mean_ci([float(r["scenes"]) for r in made]),
        "kinds": dict(sum((Counter(r["kinds"]) for r in made), Counter())),
        "textbook_scenes": sum(r["read"] for r in made), "textbook_scenes_with_verified_quote": sum(r["read_with_quote"] for r in made),
        "lessons_with_the_lecturers_voice": sum(r["hears_the_lecturer"] for r in made),
        "narration_words_per_lesson": mean_ci([float(r["narration_words"]) for r in made]),
        "narration_support": {
            "lines_judged": len(verdicts),
            "fully_supported": round(sum(v == "yes" for v in verdicts) / max(len(verdicts), 1), 4),
            "partly_supported": round(sum(v == "partly" for v in verdicts) / max(len(verdicts), 1), 4),
            "unsupported": round(sum(v == "no" for v in verdicts) / max(len(verdicts), 1), 4),
        },
        "models": {"script": sorted(models), "judge": [m for m in settings.judge_models][:1]},
        "per_concept": made,
    }
    write_result("lessons", summary)
    print({k: summary[k] for k in ("lessons_made", "scenes_kept", "scenes_dropped", "textbook_scenes", "textbook_scenes_with_verified_quote", "lessons_with_the_lecturers_voice", "narration_support")})


if __name__ == "__main__":
    main()
