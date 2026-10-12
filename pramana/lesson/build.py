"""From a storyboard to shots: finds each scene's picture in the course files and gives it a voice.

A storyboard scene names a content unit. This module opens what that unit points at (the PDF
page, the slide, the stretch of lecture video), works out where on it the cited passage and
the quoted words are, and hands `render` a shot.
"""
from __future__ import annotations

import difflib
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from ..cite import clock, place
from ..config import settings
from ..db import Database
from . import render, voice
from .render import CHALK, CITE, DIM, RATE, Shot

PAGE_SCALE = 3.0        # pages are rendered again at this scale, so a close-up stays sharp
LEAD, TAIL = 0.30, 0.45  # silence before and after a narrated line


# ---- where things are -----------------------------------------------------------------------

def raw_file(course_id: str, source: dict) -> Path:
    return settings.raw_dir / course_id / source["file"]


def page_picture(course_id: str, source: dict, page: int) -> Image.Image:
    """The page as a picture, sharp enough for a close-up; the stored preview if the PDF is gone."""
    path = raw_file(course_id, source)
    if path.exists():
        import pypdfium2 as pdfium

        return pdfium.PdfDocument(str(path))[page - 1].render(scale=PAGE_SCALE).to_pil().convert("RGB")
    return Image.open(settings.asset_dir(course_id) / source["id"] / f"p{page:04d}.jpg").convert("RGB")


def extent(db: Database, unit: dict) -> tuple[float, float, float, float]:
    """The part of the page a passage really occupies, as fractions of the page.

    A unit's stored rectangle is built from the characters of the PDF's text layer, so for a
    passage that is mostly formulas it can be a single line. The passage runs on to where the
    next unit on the page begins, across the page's text column.
    """
    x0, y0, x1, y1 = unit["locator"]["rect"]
    if unit["kind"] == "figure":
        return x0, y0, x1, y1
    others = [row["locator"]["rect"] for row in db.all(
        "SELECT locator FROM units WHERE source_id = ? AND json_extract(locator, '$.page') = ? AND id != ? AND json_extract(locator, '$.rect') IS NOT NULL",
        [unit["source_id"], unit["locator"]["page"], unit["id"]])]
    # Only units in the same column say anything about this one: on a two-column page the
    # neighbour across the gutter is a different passage.
    same = [r for r in others if min(r[2], x1) - max(r[0], x0) > 0.5 * min(r[2] - r[0], x1 - x0)]
    below = [r[1] for r in same if r[1] > y0 + 0.004]
    limit = min(below) - 0.012 if below else min(y1 + 0.22, 0.93)
    return min([x0] + [r[0] for r in same]), y0, max([x1] + [r[2] for r in same]), max(y1, min(limit, y0 + 0.42))


def quote_boxes(course_id: str, source: dict, page: int, quote: str, inside: tuple[float, float, float, float]) -> list[tuple[float, float, float, float]]:
    """Where the quoted words are printed on the page, in picture pixels: one box per line of text.

    The quote comes from the unit's text, which may differ from the PDF's own text layer by a
    line break or a formula, so it is found piece by piece: the longest run of words that the
    page holds inside the passage, then the next.
    """
    path = raw_file(course_id, source)
    words = quote.replace("$", " ").split()
    if not path.exists() or len(words) < 2:
        return []
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(path))
    sheet = document[page - 1]
    height = sheet.get_height()
    text = sheet.get_textpage()
    boxes, i = [], 0
    while i < len(words):
        for n in range(min(len(words) - i, 12), 1, -1):
            found = _find(text, " ".join(words[i: i + n]).strip(".,;:"), height, inside)
            if found:
                boxes += found
                i += n
                break
        else:
            i += 1
    return boxes


def _find(text, phrase: str, height: float, inside: tuple[float, float, float, float]) -> list[tuple[float, float, float, float]]:
    if len(phrase) < 6:
        return []
    searcher = text.search(phrase, match_case=False)
    while (hit := searcher.get_next()) is not None:
        index, count = hit
        rects = [text.get_rect(k) for k in range(text.count_rects(index, count))]
        boxes = [(l * PAGE_SCALE, (height - t) * PAGE_SCALE, r * PAGE_SCALE, (height - b) * PAGE_SCALE) for l, b, r, t in rects]
        if boxes and all(inside[0] - 6 <= (b[0] + b[2]) / 2 <= inside[2] + 6 and inside[1] - 6 <= (b[1] + b[3]) / 2 <= inside[3] + 6 for b in boxes):
            return boxes
    return []


def spoken_span(words: list[dict], start: float, end: float, quote: str, longest: float = 16.0) -> tuple[float, float] | None:
    """When, inside a lecture passage, the quoted words are said. `words` is the word-level transcript."""
    said = [w for w in words if start - 0.2 <= w["s"] <= end + 0.2]
    wanted = re.findall(r"[a-z0-9']+", quote.lower())
    tokens = [re.sub(r"[^a-z0-9']", "", w["w"].lower()) for w in said]
    if len(wanted) < 3 or len(said) < len(wanted):
        return None
    best, at = 0.0, 0
    for i in range(len(tokens) - len(wanted) + 1):
        score = difflib.SequenceMatcher(None, wanted, tokens[i: i + len(wanted)]).ratio()
        if score > best:
            best, at = score, i
    if best < 0.6:
        return None
    t0, t1 = said[at]["s"] - 0.25, said[at + len(wanted) - 1]["e"] + 0.35
    return max(t0, 0.0), min(t1, t0 + longest)


def spoken_captions(words: list[dict], t0: float, t1: float, lead: float) -> list[tuple[float, float, str]]:
    """Subtitles for a stretch of lecture, cut where the lecturer pauses or after nine words."""
    said = [w for w in words if t0 - 0.05 <= w["s"] < t1]
    out, piece = [], []
    for i, word in enumerate(said):
        piece.append(word)
        pause = i + 1 < len(said) and said[i + 1]["s"] - word["e"] > 0.45
        if len(piece) >= 9 or pause or i + 1 == len(said):
            out.append((round(piece[0]["s"] - t0 + lead, 2), round(min(piece[-1]["e"] + 0.3, t1) - t0 + lead, 2), "".join(w["w"] for w in piece).strip()))
            piece = []
    return out


# ---- sound ----------------------------------------------------------------------------------

def narration(text: str, language: str, progress: Callable[[str], None]) -> np.ndarray:
    """A narrated line at the film's sample rate, with a breath before and after it.
    Without a voice installed the line gets its reading time in silence, and the captions carry it."""
    if not voice.available():
        return _silence(LEAD + max(len(text.split()) / 2.6, 1.5) + TAIL)
    samples = voice.speak(text, language, progress=progress)
    positions = np.arange(int(len(samples) * RATE / voice.SR)) * (voice.SR / RATE)
    lifted = np.interp(positions, np.arange(len(samples)), samples).astype(np.float32) * 0.9
    return np.concatenate([np.zeros(int(LEAD * RATE), np.float32), lifted, np.zeros(int(TAIL * RATE), np.float32)])


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * RATE), np.float32)


# ---- scenes to shots ------------------------------------------------------------------------

def _short(title: str, limit: int = 44) -> str:
    return title if len(title) <= limit else title[: limit - 1].rsplit(" ", 1)[0] + "…"


def shots_for(db: Database, course_id: str, board: dict, progress: Callable[[str], None] = lambda _: None) -> list[Shot]:
    """One shot per scene of the storyboard, in order."""
    language = board.get("language", "en")
    # Voice every line first, a few at a time: synthesis is the slow step, and the lines are cached.
    lines = [scene["narration"] for scene in board["scenes"] if scene.get("narration")]
    if lines and voice.available():
        progress("voicing the narration")
        voice.speak(lines[0], language, progress=progress)          # loads the model once, before the pool starts
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda line: voice.speak(line, language), lines[1:]))
    shots: list[Shot] = []
    for index, scene in enumerate(board["scenes"], 1):
        progress(f"scene {index} of {len(board['scenes'])}")
        kind = scene["kind"]
        if kind in ("title", "end"):
            sound = narration(scene["narration"], language, progress) if scene.get("narration") else _silence(3.0)
            seconds = max(len(sound) / RATE, 3.0) + (1.2 if kind == "end" else 0.0)
            lines = [(text, face, size, {"chalk": CHALK, "dim": DIM, "cite": CITE}[colour]) for text, face, size, colour in scene["lines"]]
            shots.append(Shot(seconds, render.card(lines, rule=scene.get("rule")), sound,
                              captions=render.split_caption(scene["narration"], len(sound) / RATE - LEAD - TAIL, LEAD) if scene.get("narration") else []))
            continue
        unit = db.one("SELECT * FROM units WHERE id = ?", [scene["unit_id"]])
        source = db.one("SELECT * FROM sources WHERE id = ?", [unit["source_id"]])
        tag = f"{_short(source['title'])} · {place(unit)}"
        if kind == "listen":
            t0, t1 = scene["t0"], scene["t1"]
            tag = f"{_short(source['title'])} · {clock(t0)} · the lecturer's own words"
            from ..ingest.video import transcribe

            path = raw_file(course_id, source)
            clip = render.Clip(path, t0, t1 - t0)
            lead = 0.15
            sound = np.concatenate([_silence(lead), render.clip_audio(path, t0, t1 - t0), _silence(0.25)])
            shots.append(Shot(len(sound) / RATE, lambda t, clip=clip, lead=lead: clip.frame(t - lead), sound, tag=tag, number=scene.get("n"),
                              captions=spoken_captions(transcribe(path), t0, t1, lead)))
            continue
        sound = narration(scene["narration"], language, progress)
        seconds = len(sound) / RATE
        captions = render.split_caption(scene["narration"], seconds - LEAD - TAIL, LEAD)
        if kind == "board":
            # The lecture under the narrator. For a reading of the board, the stretch that ends with
            # the board as the reading describes it; for a spoken passage, its beginning.
            locator = unit["locator"]
            if unit["kind"] == "frame":
                end = locator.get("t_frame", locator["t_end"])
                start = max(end - seconds, locator["t_start"], 0.0)
            else:
                start, end = locator["t_start"], min(locator["t_start"] + seconds, locator["t_end"])
            clip = render.Clip(raw_file(course_id, source), start, end - start)
            draw = lambda t, clip=clip: clip.frame(t)       # noqa: E731
        elif kind == "slide":
            draw = render.slide_shot(Image.open(settings.asset_dir(course_id) / unit["asset"]).convert("RGB"), seconds)
        else:   # "read" a passage, or "look" at a figure, on a textbook page
            page = unit["locator"]["page"]
            picture = page_picture(course_id, source, page)
            x0, y0, x1, y1 = extent(db, unit)
            passage = (x0 * picture.width, y0 * picture.height, x1 * picture.width, y1 * picture.height)
            quote = quote_boxes(course_id, source, page, scene.get("focus") or "", passage) if kind == "read" else []
            draw = render.read_shot(picture, passage, quote, seconds)
        shots.append(Shot(seconds, draw, sound, tag=tag, number=scene.get("n"), captions=captions))
    return shots


def film(db: Database, course_id: str, board: dict, path: Path, progress: Callable[[str, float], None] = lambda *_: None) -> float:
    """Voice, cut and encode a storyboard. Returns the film's length in seconds."""
    shots = shots_for(db, course_id, board, lambda message: progress(message, 0.0))
    at = 0.0
    for scene, shot in zip(board["scenes"], shots):
        scene["at"], scene["seconds"] = round(at, 2), round(shot.seconds, 2)
        at += max(int(round(shot.seconds * render.FPS)), 1) / render.FPS
    return render.render(shots, path, lambda done: progress("cutting the film", done))
