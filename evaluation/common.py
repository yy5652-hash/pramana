"""Shared pieces of the evaluation scripts."""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

from pramana.config import ROOT

RESULTS = ROOT / "evaluation" / "results"
TESTSET = ROOT / "evaluation" / "testset.jsonl"


def load_testset(path: Path = TESTSET) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_result(name: str, payload: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{name}.json"
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    print(f"wrote {path}")
    return path


def same_place(unit: dict, gold: dict) -> bool:
    """Does a retrieved unit sit at the gold location: same page, same slide, or the same moment?"""
    if unit["source_id"] != gold["source_id"]:
        return False
    a, b = unit["locator"], gold["locator"]
    if "page" in b:
        return a.get("page") == b["page"]
    if "slide" in b:
        return a.get("slide") == b["slide"]
    if "t_start" in b:
        return "t_start" in a and a["t_start"] < b["t_end"] and b["t_start"] < a["t_end"]
    return unit["id"] == gold["unit_id"]


def mean_ci(values: list[float]) -> dict:
    """Mean with a normal-approximation 95 % interval. With n around 40 this is a rough guide, not a guarantee."""
    values = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not values:
        return {"mean": None, "ci95": None, "n": 0}
    half = 1.96 * statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return {"mean": round(statistics.fmean(values), 4), "ci95": round(half, 4), "n": len(values)}
