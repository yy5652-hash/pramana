"""Counts that describe a course's knowledge base and question bank."""
from __future__ import annotations

from .db import Database


def course_stats(db: Database) -> dict:
    def table(sql: str) -> dict:
        return {row["k"]: row["n"] for row in db.all(sql)}

    units = db.one("SELECT COUNT(*) AS n FROM units")["n"]
    tagged = db.one("SELECT COUNT(DISTINCT unit_id) AS n FROM unit_concepts")["n"]
    rejected: dict[str, int] = {}
    for row in db.all("SELECT verification FROM questions WHERE status = 'rejected'"):
        reason = row["verification"].get("rejected_because", "other")
        rejected[reason] = rejected.get(reason, 0) + 1
    return {
        "sources": table("SELECT kind AS k, COUNT(*) AS n FROM sources GROUP BY kind"),
        "units": units,
        "units_by_kind": table("SELECT kind AS k, COUNT(*) AS n FROM units GROUP BY kind"),
        "units_by_modality": table("SELECT modality AS k, COUNT(*) AS n FROM units GROUP BY modality"),
        "units_tagged": tagged,
        "topics": db.one("SELECT COUNT(*) AS n FROM topics")["n"],
        "concepts": db.one("SELECT COUNT(*) AS n FROM concepts")["n"],
        "prerequisite_edges": db.one("SELECT COUNT(*) AS n FROM prereqs")["n"],
        "questions_verified": table("SELECT type AS k, COUNT(*) AS n FROM questions WHERE status = 'verified' GROUP BY type"),
        "questions_by_difficulty": table("SELECT difficulty AS k, COUNT(*) AS n FROM questions WHERE status = 'verified' GROUP BY difficulty"),
        "questions_rejected": rejected,
    }
