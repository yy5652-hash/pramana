"""Organise a course into topics -> concepts -> prerequisites, and tag every unit.

Two model calls shape the map and one batched pass tags the units:

1. From the outline of all sources (textbook sections, slide titles, video titles) a model
   proposes topics, the key concepts under each, and prerequisite edges between concepts.
   The result is checked: unknown references are dropped and any edge that would close a
   cycle is removed, so the map is always a DAG.
2. Each unit is tagged with one or two concepts. Embeddings shortlist the candidates and a
   model picks among them, which keeps the choice cheap and auditable.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import numpy as np

from .. import embed
from ..config import settings
from ..llm import llm

MAP_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "concepts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                                "prerequisites": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["id", "name", "description", "prerequisites"],
                        },
                    },
                },
                "required": ["id", "title", "summary", "concepts"],
            },
        }
    },
    "required": ["topics"],
}

MAP_PROMPT = """You are organising course material into a concept map for a tutoring system.

Below is the outline of everything in the course: textbook sections with their sub-headings, slide titles and lecture-video titles.

Produce:
- 4 to 7 major topics, in teaching order. Each has an id (kebab-case), a title and a one-sentence summary.
- Under each topic, 3 to 6 key concepts a student is assessed on. Each has an id (kebab-case, unique across the course), a short name, a description (one or two sentences saying what a student who has mastered it can do), and "prerequisites": ids of concepts that must be understood first.

Rules:
- Use only what the outline covers. Do not add topics the material does not teach.
- Prerequisites must point to concepts that are taught earlier or are more basic; never form a cycle. Give direct prerequisites only (not the whole chain). A concept may have none.
- Concepts should be distinct and assessable (e.g. "Static friction", not "Miscellaneous").

Outline:
"""

TAG_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "unit": {"type": "integer"},
                    "concepts": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["unit", "concepts"],
            },
        }
    },
    "required": ["tags"],
}

TAG_PROMPT = """Tag pieces of course material with the concepts they teach.

Concepts (id: name — description):
{concepts}

For each numbered piece below, choose the one concept it mainly teaches, and a second only if it clearly teaches two. Choose from the piece's candidate list. If it teaches none of them (a preface, a biography, an exercise list, housekeeping), return an empty list.

Pieces:
{pieces}
"""


def outline(units: list[dict], sources: list[dict]) -> str:
    """A compact outline of the course built from the units themselves."""
    lines = []
    for source in sources:
        own = [u for u in units if u["source_id"] == source["id"]]
        if not own:
            continue
        lines.append(f"\n[{source['kind']}] {source['title']}")
        if source["kind"] == "video":
            continue
        seen: list[str] = []
        for unit in own:
            section = unit["section"] or ""
            if section and section not in seen:
                seen.append(section)
                lines.append(f"  {section}")
            if source["kind"] == "textbook":
                for heading in re.findall(r"^### (.+)$", unit["text"], flags=re.M):
                    if heading not in seen:
                        seen.append(heading)
                        lines.append(f"    - {heading}")
    return "\n".join(lines)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def build_map(units: list[dict], sources: list[dict]) -> dict:
    """Topics, concepts and a validated prerequisite DAG."""
    result = llm().chat(
        [{"role": "user", "content": MAP_PROMPT + outline(units, sources)}],
        models=settings.author_models,
        namespace="ingest-map",
        schema=MAP_SCHEMA,
    )
    topics, concepts, edges = [], [], []
    used: set[str] = set()
    for t_order, topic in enumerate(result.json()["topics"]):
        topic_id = _slug(topic["id"]) or f"topic-{t_order}"
        topics.append({"id": topic_id, "title": topic["title"].strip(), "summary": topic["summary"].strip(), "ord": t_order})
        for concept in topic["concepts"]:
            concept_id = _slug(concept["id"])
            if not concept_id or concept_id in used:
                continue
            used.add(concept_id)
            concepts.append({
                "id": concept_id, "topic_id": topic_id, "name": concept["name"].strip(),
                "description": concept["description"].strip(), "ord": len(concepts),
                "_requires": [_slug(p) for p in concept["prerequisites"]],
            })
    order = {c["id"]: c["ord"] for c in concepts}
    for concept in concepts:
        for required in concept.pop("_requires"):
            # Teaching order doubles as a topological order: an edge may only point backwards.
            if required in order and order[required] < order[concept["id"]]:
                edges.append({"concept_id": concept["id"], "requires_id": required})
    return {"topics": topics, "concepts": concepts, "prereqs": edges, "model": result.model}


def tag_units(
    units: list[dict],
    concepts: list[dict],
    vectors: np.ndarray,
    progress: Callable[[str], None] = print,
    batch: int = 24,
    shortlist: int = 6,
    workers: int = 4,
) -> list[dict]:
    """Rows for `unit_concepts`. `vectors` are the units' embeddings, row-aligned with `units`."""
    concept_vectors = embed.embed_passages([f"{c['name']}: {c['description']}" for c in concepts])
    similarity = vectors @ concept_vectors.T
    catalogue = "\n".join(f"{c['id']}: {c['name']} — {c['description']}" for c in concepts)
    known = {c["id"] for c in concepts}

    def tag(start: int) -> list[dict]:
        rows = []
        pieces = []
        chunk = list(range(start, min(start + batch, len(units))))
        candidates: dict[int, list[str]] = {}
        for local, index in enumerate(chunk, 1):
            top = [concepts[j]["id"] for j in np.argsort(-similarity[index])[:shortlist]]
            candidates[local] = top
            snippet = " ".join(units[index]["text"].split())[:420]
            pieces.append(f"{local}. [{units[index]['section'] or ''}] {snippet}\n   candidates: {', '.join(top)}")
        result = llm().chat(
            [{"role": "user", "content": TAG_PROMPT.format(concepts=catalogue, pieces="\n".join(pieces))}],
            models=settings.bulk_models,
            namespace="ingest-tags",
            schema=TAG_SCHEMA,
        )
        for entry in result.json().get("tags", []):
            local = entry.get("unit")
            if local not in candidates:
                continue
            chosen = [c for c in (_slug(x) for x in entry.get("concepts", [])) if c in known][:2]
            for rank, concept_id in enumerate(chosen):
                rows.append({"unit_id": units[chunk[local - 1]]["id"], "concept_id": concept_id, "weight": 1.0 if rank == 0 else 0.5})
        return rows

    rows: list[dict] = []
    starts = list(range(0, len(units), batch))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, batch_rows in enumerate(pool.map(tag, starts), 1):
            rows.extend(batch_rows)
            if done % 10 == 0 or done == len(starts):
                progress(f"tagged {min(done * batch, len(units))}/{len(units)} units")
    return rows
