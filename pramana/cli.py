"""Command line: `pramana fetch|ingest|organise|bank|lesson|serve|stats`."""
from __future__ import annotations

import argparse
import json
import sys
import time


def _log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pramana", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser("fetch", help="download the open sources named in a course manifest")
    fetch.add_argument("course")
    fetch.add_argument("--only", nargs="*", help="source ids")

    ingest = commands.add_parser("ingest", help="read sources into the knowledge base")
    ingest.add_argument("course")
    ingest.add_argument("--only", nargs="*", help="source ids")
    ingest.add_argument("--no-vision", action="store_true", help="text layer only (the evaluation's ablation)")
    ingest.add_argument("--no-organise", action="store_true", help="skip the concept map step")
    ingest.add_argument("--as", dest="target", help="store the knowledge base under this course id")

    organise = commands.add_parser("organise", help="rebuild topics, concepts, prerequisites and unit tags")
    organise.add_argument("course")

    bank = commands.add_parser("bank", help="generate and verify questions for every concept")
    bank.add_argument("course")
    bank.add_argument("--rounds", type=int, default=2)

    lesson = commands.add_parser("lesson", help="cut a lesson film on one concept for one student")
    lesson.add_argument("course")
    lesson.add_argument("--student", default="Asha", help="student name; created if new")
    lesson.add_argument("--concept", help="concept id; default is the one the learner model recommends")

    serve = commands.add_parser("serve", help="run the web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    stats = commands.add_parser("stats", help="print knowledge-base and question-bank counts")
    stats.add_argument("course")

    args = parser.parse_args(argv)

    if args.command == "fetch":
        from .fetch import fetch_course

        fetch_course(args.course, set(args.only) if args.only else None)
    elif args.command == "ingest":
        from .ingest import build_course

        build_course(args.course, _log, set(args.only) if args.only else None,
                     use_vision=not args.no_vision, organise_after=not args.no_organise, target=args.target)
    elif args.command == "organise":
        from .db import open_course
        from .ingest import organise as run_organise

        run_organise(open_course(args.course), _log)
    elif args.command == "bank":
        from .assess.generate import build_bank
        from .db import open_course

        print(json.dumps(build_bank(open_course(args.course), args.rounds, _log), indent=2))
    elif args.command == "lesson":
        from . import lesson as lessons
        from .db import new_id, now, open_course
        from .retrieve import index_for

        db = open_course(args.course)
        student = db.one("SELECT * FROM students WHERE name = ? ORDER BY created DESC", [args.student])
        if not student:
            student = {"id": new_id("s"), "name": args.student, "created": now(), "profile": {}}
            db.insert("students", student)
        board = lessons.make(db, index_for(args.course, db), args.course, student["id"], args.concept,
                             progress=lambda step, done: _log(f"{step} {done:.0%}" if done else step))
        _log(f"{board['concept']}: {board['seconds']} s, {len(board['scenes']) - 2} scenes -> data/kb/{args.course}/assets/lessons/{board['id']}.mp4")
    elif args.command == "serve":
        import uvicorn

        uvicorn.run("pramana.api:app", host=args.host, port=args.port, log_level="info")
    elif args.command == "stats":
        from .db import open_course
        from .stats import course_stats

        print(json.dumps(course_stats(open_course(args.course)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
