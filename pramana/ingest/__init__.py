"""Ingestion: raw course files -> knowledge base.

    files ──► units (pdf.py / slides.py / video.py) ──► embeddings ──► concept map + tags

Every step is idempotent. Model replies and transcripts are cached, so running it again
costs nothing, and running it on another machine with `PRAMANA_LLM_MODE=replay` rebuilds the
same knowledge base without an API key.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np

from .. import embed
from ..config import settings
from ..db import Database, open_course
from ..fetch import load_manifest
from . import concepts as concept_map
from .pdf import ingest_pdf
from .slides import ingest_slides
from .video import ingest_video

SUFFIX_KIND = {".pdf": "textbook", ".pptx": "slides", ".mp4": "video", ".mov": "video", ".mkv": "video", ".webm": "video"}


def ingest_source(source: dict, path: Path, asset_root: Path, progress: Callable[[str], None] = print,
                  use_vision: bool = True) -> list[dict]:
    """Units for one file. The kind decides the reader; nothing about the file is prepared by hand."""
    asset_dir = asset_root / source["id"]
    kind = source.get("kind") or SUFFIX_KIND.get(path.suffix.lower())
    if path.suffix.lower() == ".pdf":  # textbooks and decks exported to PDF take the same path
        units = ingest_pdf(source, path, asset_dir, progress, text_layer_only=not use_vision)
        if kind == "slides":
            for unit in units:
                unit["kind"] = "slide" if unit["kind"] == "text" else unit["kind"]
                unit["locator"]["slide"] = unit["locator"]["page"]
        return units
    if kind == "slides":
        return ingest_slides(source, path, asset_dir, progress, use_vision=use_vision)
    if kind == "video":
        return ingest_video(source, path, asset_dir, progress, use_vision=use_vision)
    raise ValueError(f"unsupported source: {path.name}")


def store_units(db: Database, source: dict, units: list[dict]) -> None:
    """Replace a source's units and their embeddings."""
    db.insert("sources", {
        "id": source["id"], "kind": source["kind"], "title": source["title"], "file": source["file"],
        "licence": source.get("licence", ""), "attribution": " ".join(source.get("attribution", "").split()),
        "meta": {k: source[k] for k in ("url", "youtube", "chapters") if k in source},
    }, replace=True)
    old = [r["id"] for r in db.all("SELECT id FROM units WHERE source_id = ?", [source["id"]])]
    for unit_id in old:
        db.run("DELETE FROM embeddings WHERE unit_id = ?", [unit_id])
        db.run("DELETE FROM unit_concepts WHERE unit_id = ?", [unit_id])
    db.run("DELETE FROM units WHERE source_id = ?", [source["id"]])
    db.insert_many("units", units)
    vectors = embed.embed_passages([f"{u['section'] or ''}\n{u['text']}" for u in units])
    db.insert_many("embeddings", [{"unit_id": u["id"], "vec": embed.to_blob(v)} for u, v in zip(units, vectors)])


def organise(db: Database, progress: Callable[[str], None] = print) -> dict:
    """(Re)build topics, concepts, prerequisites and unit tags from the stored units."""
    units = db.all("SELECT * FROM units ORDER BY source_id, ord")
    sources = db.all("SELECT * FROM sources ORDER BY kind = 'textbook' DESC, kind = 'slides' DESC, id")
    course_map = concept_map.build_map(units, sources)
    for table in ("unit_concepts", "prereqs"):
        db.run(f"DELETE FROM {table}")
    # Concepts are replaced in place so that questions and mastery rows that reference a
    # surviving id stay valid.
    db.run("PRAGMA foreign_keys=OFF")
    db.run("DELETE FROM concepts")
    db.run("DELETE FROM topics")
    db.insert_many("topics", course_map["topics"])
    db.insert_many("concepts", course_map["concepts"])
    db.insert_many("prereqs", course_map["prereqs"])
    db.run("PRAGMA foreign_keys=ON")
    vectors = {r["unit_id"]: embed.from_blob(r["vec"]) for r in db.all("SELECT unit_id, vec FROM embeddings")}
    matrix = np.stack([vectors[u["id"]] for u in units])
    rows = concept_map.tag_units(units, course_map["concepts"], matrix, progress)
    db.insert_many("unit_concepts", rows, replace=True)
    progress(f"map: {len(course_map['topics'])} topics, {len(course_map['concepts'])} concepts, "
             f"{len(course_map['prereqs'])} prerequisite edges, {len({r['unit_id'] for r in rows})}/{len(units)} units tagged")
    return course_map


def build_course(course_id: str, progress: Callable[[str], None] = print, only: set[str] | None = None,
                 use_vision: bool = True, organise_after: bool = True, target: str | None = None) -> Database:
    """Build the knowledge base for a course manifest. `target` stores it under another id,
    which is how the evaluation keeps a no-vision copy next to the real one."""
    manifest = load_manifest(course_id)
    raw = settings.raw_dir / course_id
    course_id = target or course_id
    db = open_course(course_id)
    for source in manifest["sources"]:
        if only and source["id"] not in only:
            continue
        path = raw / source["file"]
        if not path.exists():
            progress(f"skip {source['id']}: {path.name} not downloaded (run `pramana fetch {course_id}`)")
            continue
        units = ingest_source(source, path, settings.asset_dir(course_id), progress, use_vision)
        store_units(db, source, units)
        progress(f"stored {source['id']}: {len(units)} units")
    if organise_after:
        organise(db, progress)
    return db
