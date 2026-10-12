"""Copies what the film shows out of the real project: footage, page and slide renders, and
the numbers. Every figure in the film is read from `film/public/data/film.json`, which this
script writes from the knowledge base and from `evaluation/results/*.json`.

    <pramana>/.venv/bin/python tools/export_data.py
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
# The product repository: this folder lives inside it as demo-film/, or beside it while the film is being made.
PRAMANA = next(p for p in (HERE.parents[2], HERE.parents[2] / "pramana") if (p / "pramana" / "__init__.py").exists())
FILM = Path(__file__).resolve().parent.parent / "film"
sys.path.insert(0, str(PRAMANA))

import pypdfium2 as pdfium  # noqa: E402
import pypdfium2.raw as pdfium_raw  # noqa: E402

from pramana.config import settings  # noqa: E402
from pramana.db import open_course  # noqa: E402
from pramana.stats import course_stats  # noqa: E402

COURSE = "mechanics"
FOOTAGE = ["MIT8_01F16_L04v01_360p.mp4", "MIT8_01F16_L06v02_360p.mp4", "MIT8_01F16_L20v05_360p.mp4", "MIT8_01F16_L02v02_360p.mp4", "MIT8_01F16_L20v01_360p.mp4"]
PAGES = [128, 215, 216, 217, 223, 278]
SLIDES = [("slides-ch5", 13), ("slides-ch6", 15)]
TEXT_LAYER_PAGE = 128   # the page whose text layer visibly lacks its equations
XRAY = {"x": (14.0, 598.0), "y": (33.5, 362.0)}       # the 16:9 part of that page the film fills the frame with, in points
SLIDE_READ = "slides-ch6:s15"                         # a slide whose figure the vision pass described
BOARD_READ = "v-l06v02:f101"                          # a board the vision pass read


def xray(pdf, page_number: int, units: list[dict]) -> dict:
    """What page `page_number` holds as text and what it holds as drawings.

    `lines` are the runs of the PDF's own text layer with their positions; `holes` are the
    clusters of vector paths that draw the formulas, each paired with the LaTeX the vision
    pass stored for it. Positions are fractions of the XRAY region.
    """
    page = pdf[page_number - 1]
    width, height = page.get_size()
    text = page.get_textpage()
    (x0, x1), (y0, y1) = XRAY["x"], XRAY["y"]
    inside = lambda box: box[0] >= x0 and box[2] <= x1 and box[1] >= y0 and box[3] <= y1   # noqa: E731
    frac = lambda box: [round((box[0] - x0) / (x1 - x0), 4), round((box[1] - y0) / (y1 - y0), 4),   # noqa: E731
                        round((box[2] - x0) / (x1 - x0), 4), round((box[3] - y0) / (y1 - y0), 4)]

    # the text layer: characters -> lines -> runs (a wide gap inside a line is where an inline formula was drawn)
    chars = []
    for index in range(text.count_chars()):
        if not text.get_text_range(index, 1).strip():
            continue
        left, bottom, right, top = text.get_charbox(index)
        chars.append((left, height - top, right, height - bottom))
    chars.sort(key=lambda c: ((c[1] + c[3]) / 2, c[0]))
    rows: list[list[tuple]] = []
    for char in chars:
        middle = (char[1] + char[3]) / 2
        if rows and abs((rows[-1][-1][1] + rows[-1][-1][3]) / 2 - middle) < 4:
            rows[-1].append(char)
        else:
            rows.append([char])
    lines = []
    for row in rows:
        row.sort(key=lambda c: c[0])
        runs = [[row[0]]]
        for char in row[1:]:
            if char[0] - runs[-1][-1][2] > 9:
                runs.append([char])
            else:
                runs[-1].append(char)
        for run in runs:
            box = (min(c[0] for c in run), min(c[1] for c in run), max(c[2] for c in run), max(c[3] for c in run))
            if not inside(box):
                continue
            words = text.get_text_bounded(box[0] - 0.5, height - box[3] - 0.5, box[2] + 0.5, height - box[1] + 0.5)
            lines.append({"t": " ".join(words.split()), "r": frac(box)})

    # the drawings: path objects, joined into one cluster per formula
    paths = []
    for obj in page.get_objects(filter=[pdfium_raw.FPDF_PAGEOBJ_PATH], max_depth=4):
        left, bottom, right, top = obj.get_bounds()
        if right - left < 300 and top - bottom < 200:          # not a rule or a shaded panel
            paths.append([left, height - top, right, height - bottom, 1])
    merged = True
    while merged:
        merged = False
        for a in paths:
            for b in paths:
                if a is not b and a[0] - b[2] <= 7 and b[0] - a[2] <= 7 and a[1] - b[3] <= 8 and b[1] - a[3] <= 8:
                    a[:] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]), a[4] + b[4]]
                    paths.remove(b)
                    merged = True
                    break
            if merged:
                break
    paths.sort(key=lambda c: (c[1], c[0]))
    formulas = [(m.group(1) or m.group(2), m.group(1) is None) for u in units for m in re.finditer(r"\$\$\s*(.+?)\s*\$\$|\$([^$]+)\$", u["text"], re.S)]
    holes = [{"r": frac(c), "paths": c[4], "tex": tex, "inline": inline} for c, (tex, inline) in zip(paths, formulas) if inside(c)]
    return {"page": page_number, "image": f"pages/p{page_number:04d}@4x.jpg", "size": [width, height],
            "crop": [x0 / width, y0 / height, x1 / width, y1 / height], "lines": lines, "holes": holes,
            "paths_on_page": sum(c[4] for c in paths)}


def reading(db, unit_id: str) -> dict:
    """What the vision pass stored for one slide or board: its description and its formulas."""
    unit = db.one("SELECT id, source_id, locator, section, text, asset FROM units WHERE id = ?", [unit_id])
    text = unit["text"]
    marker = re.search(r"(?:Equations on the slide|Written on the board): (.+)", text)
    figure = re.search(r"Figure on the slide: (.+)", text, re.S)
    return {"id": unit_id, "locator": unit["locator"], "section": unit["section"], "text": text,
            "equations": re.findall(r"\$([^$]+)\$", marker.group(1)) if marker else [],
            "figure": " ".join(figure.group(1).split()) if figure else ""}


def main() -> None:
    db = open_course(COURSE)
    public = FILM / "public"
    for sub in ("footage", "pages", "slides", "data", "frames"):
        (public / sub).mkdir(parents=True, exist_ok=True)
    raw = settings.raw_dir / COURSE
    assets = settings.asset_dir(COURSE)
    for name in FOOTAGE:
        if not (public / "footage" / name).exists():
            shutil.copyfile(raw / name, public / "footage" / name)
    for page in PAGES:
        shutil.copyfile(assets / "textbook" / f"p{page:04d}.jpg", public / "pages" / f"p{page:04d}.jpg")
    for deck, number in SLIDES:
        shutil.copyfile(assets / deck / f"s{number:03d}.jpg", public / "slides" / f"{deck}-s{number:03d}.jpg")

    # Sharper page renders for close-ups (the app's own are 1.6x; these are 3x).
    pdf = pdfium.PdfDocument(str(raw / "university-physics-volume-1.pdf"))
    for page in PAGES:
        target = public / "pages" / f"p{page:04d}@3x.jpg"
        if not target.exists():
            pdf[page - 1].render(scale=3).to_pil().convert("RGB").save(target, quality=90)
    text_layer = pdf[TEXT_LAYER_PAGE - 1].get_textpage().get_text_range()
    sharp = public / "pages" / f"p{TEXT_LAYER_PAGE:04d}@4x.jpg"
    if not sharp.exists():
        pdf[TEXT_LAYER_PAGE - 1].render(scale=4).to_pil().convert("RGB").save(sharp, quality=92)

    stats = course_stats(db)
    units = db.all("SELECT id, kind, modality, locator, section, text FROM units WHERE source_id = 'textbook' AND json_extract(locator, '$.page') = ? ORDER BY ord", [TEXT_LAYER_PAGE])
    board = db.all("SELECT id, locator, text, asset FROM units WHERE kind = 'frame' AND source_id = 'v-l04v01' ORDER BY ord")
    for unit in board:
        shutil.copyfile(assets / unit["asset"], public / "frames" / Path(unit["asset"]).name)
    results = {}
    for path in sorted((PRAMANA / "evaluation" / "results").glob("*.json")):
        payload = json.loads(path.read_text())
        payload.pop("per_question", None)
        results[path.stem] = payload
    concepts = db.all("SELECT id, topic_id, name, ord FROM concepts ORDER BY ord")
    film = {
        "stats": stats,
        "vision_share": round(stats["units_by_modality"].get("vision", 0) / stats["units"], 4),
        "text_layer": {"page": TEXT_LAYER_PAGE, "raw": text_layer, "units": units},
        "board": [{"id": u["id"], "t_frame": u["locator"]["t_frame"], "text": u["text"], "frame": Path(u["asset"]).name} for u in board],
        "map": {"topics": db.all("SELECT id, title FROM topics ORDER BY ord"), "concepts": concepts, "prereqs": db.all("SELECT * FROM prereqs")},
        "results": results,
        "xray": xray(pdf, TEXT_LAYER_PAGE, units),
        "slide_read": reading(db, SLIDE_READ),
        "board_read": reading(db, BOARD_READ),
        # one letter per citable piece, in course order: t = text layer, v = read by vision, s = speech
        "unit_marks": "".join({"text": "t", "vision": "v", "speech": "s"}[u["modality"]] for u in db.all("SELECT modality FROM units ORDER BY rowid")),
    }
    (public / "data" / "film.json").write_text(json.dumps(film, indent=1, ensure_ascii=False))
    print(f"wrote {public / 'data' / 'film.json'}: {stats['units']} units, vision share {film['vision_share']:.0%}, results: {sorted(results)}")


if __name__ == "__main__":
    main()
