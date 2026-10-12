"""Lessons: a short narrated film on one concept, cut from the course's own pages, slides and lectures.

    script.py   chooses the sources and writes the narration (one model call), then keeps only
                the scenes that can be tied to a source
    build.py    finds each scene's picture in the course files and gives it a voice
    render.py   draws and encodes the film (Pillow and PyAV; no external tools)
    voice.py    the narrator (Kokoro-82M, local)
"""
from __future__ import annotations

from typing import Callable

from ..config import settings
from ..db import Database
from ..retrieve import Index
from . import build, script
from .script import NotEnoughMaterial, next_concept  # noqa: F401


def make(db: Database, index: Index, course_id: str, student_id: str, concept_id: str | None = None, language: str = "en",
         progress: Callable[[str, float], None] = lambda *_: None) -> dict:
    """Write, voice and cut a lesson for this student; store it and return its storyboard."""
    progress("choosing sources and writing the narration", 0.0)
    board = script.write(db, index, course_id, student_id, concept_id, language)
    path = settings.asset_dir(course_id) / "lessons" / f"{board['id']}.mp4"
    board["seconds"] = round(build.film(db, course_id, board, path, progress), 1)
    board["video"] = f"/assets/{course_id}/lessons/{path.name}"
    db.insert("lessons", {"id": board["id"], "student_id": student_id, "concept_id": board["concept_id"], "created": board["created"], "board": board})
    return board
