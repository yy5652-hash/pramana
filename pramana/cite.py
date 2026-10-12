"""Citations: turn a content unit into something a reader can open at the exact place."""
from __future__ import annotations

import re

from .db import Database


def clock(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def place(unit: dict) -> str:
    """Human-readable location inside the source: 'p. 214', 'slide 12', '2:13'."""
    locator = unit["locator"]
    if "t_start" in locator:
        return clock(locator.get("t_frame", locator["t_start"]) if unit["kind"] == "frame" else locator["t_start"])
    if "slide" in locator:
        return f"slide {locator['slide']}"
    label = f"p. {locator['page']}"
    if unit["kind"] == "figure" and locator.get("label"):
        label += f", {locator['label']}"
    return label


def plain_start(text: str, limit: int = 320) -> str:
    """The beginning of a unit as running text: headings folded in, line breaks collapsed."""
    flat = " ".join(re.sub(r"^### (.+)$", r"\1.", text, flags=re.M).split())
    return flat if len(flat) <= limit else _close_maths(flat[: limit - 1].rsplit(" ", 1)[0] + "…")


def best_excerpt(text: str, claim: str, limit: int = 320) -> str:
    """The sentence(s) of `text` that share the most content words with `claim`."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z$\\(])|\n{2,}", text) if s.strip() and not s.startswith("### ")]
    if not sentences:
        return text[:limit]
    wanted = {w for w in re.findall(r"[a-z0-9]+", claim.lower()) if len(w) > 3}

    def overlap(sentence: str) -> int:
        return len(wanted & set(re.findall(r"[a-z0-9]+", sentence.lower())))

    best = max(range(len(sentences)), key=lambda i: (overlap(sentences[i]), -i))
    excerpt = sentences[best]
    if len(excerpt) < 120 and best + 1 < len(sentences):
        excerpt += " " + sentences[best + 1]
    if len(excerpt) > limit:
        excerpt = excerpt[: limit - 1].rsplit(" ", 1)[0] + "…"
    return _close_maths(excerpt)


def _close_maths(text: str) -> str:
    """Drop a formula that the cut left open, so an excerpt never ends in half a LaTeX expression."""
    for delimiter in ("$$", "$"):
        rest = text.replace("$$", "") if delimiter == "$" else text
        if rest.count(delimiter) % 2:
            text = text[: text.rfind(delimiter)].rstrip() + "…"
    return text


def citation(course_id: str, unit: dict, source: dict, claim: str = "") -> dict:
    locator = unit["locator"]
    return {
        "unit_id": unit["id"],
        "source_id": source["id"],
        "source_title": source["title"],
        "source_kind": source["kind"],
        "kind": unit["kind"],
        "modality": unit["modality"],
        "place": place(unit),
        "label": f"{source['title']}, {place(unit)}",
        "section": unit["section"],
        "locator": locator,
        "asset": f"/assets/{course_id}/{unit['asset']}" if unit.get("asset") else None,
        "page_image": f"/assets/{course_id}/{source['id']}/p{locator['page']:04d}.jpg" if "page" in locator else None,
        "media": f"/media/{course_id}/{source['file']}" if source["kind"] == "video" else None,
        "excerpt": best_excerpt(unit["text"], claim) if claim else plain_start(unit["text"]),
        "licence": source.get("licence", ""),
    }


def citations_for(db: Database, course_id: str, unit_ids: list[str], claim: str = "") -> list[dict]:
    out = []
    for unit_id in unit_ids:
        unit = db.one("SELECT * FROM units WHERE id = ?", [unit_id])
        if unit:
            source = db.one("SELECT * FROM sources WHERE id = ?", [unit["source_id"]])
            out.append(citation(course_id, unit, source, claim))
    return out


def study_links(db: Database, course_id: str, concept_id: str, limit: int = 3) -> list[dict]:
    """Where to study a concept: the best-tagged unit from each kind of source."""
    rows = db.all(
        "SELECT u.*, s.kind AS source_kind FROM units u JOIN unit_concepts uc ON uc.unit_id = u.id "
        "JOIN sources s ON s.id = u.source_id WHERE uc.concept_id = ? ORDER BY uc.weight DESC, u.source_id, u.ord",
        [concept_id])
    picked, kinds = [], set()
    for row in rows:
        if row["source_kind"] not in kinds:
            kinds.add(row["source_kind"])
            picked.append(row["id"])
        if len(picked) >= limit:
            break
    return citations_for(db, course_id, picked)
