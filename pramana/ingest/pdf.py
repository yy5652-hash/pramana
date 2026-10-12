"""Textbooks and PDF slide decks -> citable content units.

Each page is rendered once, read by the vision model (see `vision.py`), and split into
units. A unit never crosses a page, so a citation can open one page and highlight one
rectangle on it.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw

from . import vision
from .common import file_digest

RENDER_SCALE = 1.6
TARGET_WORDS = 150
# Back-of-chapter exercise lists are not teaching material; citing them would be noise.
STOP_HEADINGS = ("conceptual questions", "problems", "additional problems", "challenge problems")


def table_of_contents(pdf: pdfium.PdfDocument) -> list[tuple[int, int, str]]:
    """(level, page index, title) for every bookmark that points at a page."""
    entries = []
    for item in pdf.get_toc():
        title = item.get_title() if hasattr(item, "get_title") else item.title
        if hasattr(item, "get_dest"):
            dest = item.get_dest()
            page = dest.get_index() if dest else None
        else:
            page = item.page_index
        if page is not None:
            entries.append((item.level, page, title.strip()))
    return entries


def chapter_ranges(pdf: pdfium.PdfDocument, chapters: list[int] | None) -> list[tuple[int, int, str]]:
    """(first page, last page, chapter title). Without `chapters`, the whole document."""
    toc = table_of_contents(pdf)
    if not chapters:
        return [(0, len(pdf) - 1, "")]
    tops = [(page, title) for level, page, title in toc if level == 0]
    ranges = []
    for position, (page, title) in enumerate(tops):
        match = re.match(r"Chapter (\d+)\b", title)
        if match and int(match.group(1)) in chapters:
            last = tops[position + 1][0] - 1 if position + 1 < len(tops) else len(pdf) - 1
            ranges.append((page, last, title))
    return ranges


def _normalise(text: str) -> tuple[str, list[int]]:
    """Lower-case, single-spaced copy of `text` plus a map back to original character indices."""
    out, index_map, previous_space = [], [], True
    for index, char in enumerate(text):
        if char.isspace():
            if not previous_space:
                out.append(" ")
                index_map.append(index)
            previous_space = True
        else:
            out.append(char.lower())
            index_map.append(index)
            previous_space = False
    return "".join(out), index_map


def _plain_spans(markdown: str) -> list[str]:
    """Runs of ordinary words in a block, i.e. the parts that also exist in the text layer."""
    spans = re.split(r"\$\$.*?\$\$|\$[^$]*\$|\\\(.*?\\\)", markdown, flags=re.S)
    return [" ".join(s.replace("*", " ").replace("#", " ").split()) for s in spans]


def _anchor(pieces: list[str], from_end: bool) -> str | None:
    """Five consecutive plain words taken from the start (or end) of the unit."""
    order = reversed(pieces) if from_end else pieces
    for piece in order:
        spans = _plain_spans(piece)
        for span in (reversed(spans) if from_end else spans):
            words = span.split()
            if len(words) >= 4:
                return " ".join(words[-5:] if from_end else words[:5]).lower()
    return None


class _PageText:
    def __init__(self, page: pdfium.PdfPage):
        self.width, self.height = page.get_size()
        self.textpage = page.get_textpage()
        self.text = self.textpage.get_text_range()
        self.normal, self.index_map = _normalise(self.text)
        self.cursor = 0

    def rect_for(self, pieces: list[str]) -> list[float] | None:
        """Bounding box [x0, y0, x1, y1] (0-1, origin top-left) of a unit's prose on the page."""
        first, last = _anchor(pieces, False), _anchor(pieces, True)
        if not first:
            return None
        start = self.normal.find(first, self.cursor)
        if start < 0:
            start = self.normal.find(first)
        if start < 0:
            return None
        end = self.normal.find(last, start) if last else -1
        end = end + len(last) if end >= 0 else start + len(first)
        self.cursor = start + len(first)
        boxes = []
        for position in range(start, min(end, len(self.index_map))):
            if self.normal[position] == " ":
                continue
            left, bottom, right, top = self.textpage.get_charbox(self.index_map[position])
            if right > left and top > bottom:
                boxes.append((left, bottom, right, top))
        if not boxes:
            return None
        x0, x1 = min(b[0] for b in boxes), max(b[2] for b in boxes)
        y_top, y_bottom = max(b[3] for b in boxes), min(b[1] for b in boxes)
        return [
            round(x0 / self.width, 4),
            round(1 - y_top / self.height, 4),
            round(x1 / self.width, 4),
            round(1 - y_bottom / self.height, 4),
        ]


def _image_boxes(page: pdfium.PdfPage) -> list[list[float]]:
    width, height = page.get_size()
    boxes = []
    for obj in page.get_objects(filter=[pdfium_raw.FPDF_PAGEOBJ_IMAGE]):
        left, bottom, right, top = obj.get_bounds()
        if (right - left) * (top - bottom) > 0.01 * width * height:
            boxes.append([left / width, 1 - top / height, right / width, 1 - bottom / height])
    return boxes


def _overlap(a: list[float], b: list[float]) -> float:
    """Share of box `b` that lies inside box `a`."""
    width = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = (b[2] - b[0]) * (b[3] - b[1])
    return width * height / area if area > 0 else 0.0


def _figure_box(model_box: list[int] | None, images: list[list[float]]) -> list[float] | None:
    """Prefer the exact bounds of embedded images; fall back to the model's estimate."""
    if not model_box or len(model_box) != 4:
        return None
    ymin, xmin, ymax, xmax = (max(0, min(1000, v)) / 1000 for v in model_box)
    if ymax <= ymin or xmax <= xmin:
        return None
    estimate = [xmin, ymin, xmax, ymax]
    grown = [xmin - 0.04, ymin - 0.04, xmax + 0.04, ymax + 0.04]
    inside = [box for box in images if _overlap(grown, box) > 0.6]
    if inside:
        return [
            round(min(b[0] for b in inside), 4),
            round(min(b[1] for b in inside), 4),
            round(max(b[2] for b in inside), 4),
            round(max(b[3] for b in inside), 4),
        ]
    return [round(v, 4) for v in estimate]


def _block_markdown(block: dict) -> str:
    text = block["text"].strip()
    kind = block["type"]
    if kind == "equation":
        label = f" ({block['label']})" if block.get("label") else ""
        return f"$$ {text} $${label}"
    if kind == "heading":
        return f"### {text}"
    if kind == "example":
        return text if text.lower().startswith("example") else f"Example: {text}"
    return text


def ingest_pdf(
    source: dict,
    path: Path,
    asset_dir: Path,
    progress: Callable[[str], None] = print,
    text_layer_only: bool = False,
    workers: int = 4,
) -> list[dict]:
    """Return content units for a PDF. `text_layer_only` is the no-vision ablation used in the evaluation."""
    pdf = pdfium.PdfDocument(str(path))
    digest = file_digest(path)
    asset_dir.mkdir(parents=True, exist_ok=True)
    toc_sections = {page: title for level, page, title in table_of_contents(pdf) if re.match(r"\d+\.\d+\s", title)}
    ranges = chapter_ranges(pdf, source.get("chapters"))

    # Pass 1 (main thread; pdfium is not thread-safe): render every page, read its text layer.
    pages: dict[int, tuple[Path, _PageText, list[list[float]]]] = {}
    trimmed = []
    for first, last, chapter in ranges:
        for page_index in range(first, last + 1):
            page = pdf[page_index]
            page_text = _PageText(page)
            image_path = asset_dir / f"p{page_index + 1:04d}.jpg"
            if not image_path.exists():
                page.render(scale=RENDER_SCALE).to_pil().convert("RGB").save(image_path, quality=80)
            pages[page_index] = (image_path, page_text, _image_boxes(page))
            # The exercise lists that close a chapter are not read at all: stop at their first page.
            if any(line.strip().lower() in STOP_HEADINGS for line in page_text.text.splitlines()):
                last = page_index
                break
        trimmed.append((first, last, chapter))
    ranges = trimmed

    # Pass 2 (thread pool): one vision call per page. Replies are cached, so a re-run is instant.
    blocks_by_page: dict[int, list[dict]] = {}
    if text_layer_only:
        for page_index, (_, page_text, _) in pages.items():
            blocks_by_page[page_index] = [{"type": "paragraph", "text": p} for p in _paragraphs(page_text.text)]
    else:
        def read(page_index: int) -> tuple[int, list[dict]]:
            image_path, page_text, _ = pages[page_index]
            blocks, _ = vision.read_page(
                image_path, page_text.text, cache_key=["page", vision.PAGE_PROMPT_VERSION, digest, page_index]
            )
            return page_index, blocks

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for done, (page_index, blocks) in enumerate(pool.map(read, pages), 1):
                blocks_by_page[page_index] = blocks
                if done % 10 == 0 or done == len(pages):
                    progress(f"{source['id']}: read {done}/{len(pages)} pages")

    # Pass 3: split each page's blocks into units.
    canonical = {title.split()[0]: title for title in toc_sections.values()}
    units: list[dict] = []
    for first, last, chapter in ranges:
        section = chapter
        for page_index in range(first, last + 1):
            image_path, page_text, images = pages[page_index]
            page_units, section, stopped = _page_units(
                source["id"], page_index, blocks_by_page[page_index], page_text, images, image_path,
                asset_dir, section, text_layer_only, canonical,
            )
            units.extend(page_units)
            outline = toc_sections.get(page_index)
            # If the model missed a numbered section heading, the outline still knows it started here.
            if outline and outline.split()[0] != section.split()[0]:
                section = outline
            if stopped:
                break
    for order, unit in enumerate(units):
        unit["ord"] = order
    return units


def _page_units(
    source_id: str,
    page_index: int,
    blocks: list[dict],
    page_text: _PageText,
    images: list[list[float]],
    image_path: Path,
    asset_dir: Path,
    section: str,
    text_layer_only: bool,
    canonical: dict[str, str],
) -> tuple[list[dict], str, bool]:
    """Units for one page, the section in force at its end, and whether an exercise list began."""
    page_number = page_index + 1
    asset = f"{source_id}/{image_path.name}"
    units: list[dict] = []
    pending: list[str] = []
    words = 0
    figures = 0

    def flush() -> None:
        nonlocal pending, words
        text = "\n\n".join(pending)
        if len(text.split()) >= 8:
            rect = page_text.rect_for(pending)
            units.append({
                "id": f"{source_id}:p{page_number}:{sum(1 for u in units if u['kind'] == 'text') + 1}",
                "source_id": source_id,
                "kind": "text",
                "modality": "text" if text_layer_only or "$" not in text else "vision",
                "locator": {"page": page_number, **({"rect": rect} if rect else {})},
                "section": section,
                "text": text,
                "asset": asset,
            })
        pending, words = [], 0

    for position, block in enumerate(blocks):
        text = block["text"].strip()
        if block["type"] == "heading":
            flush()
            if text.lower().strip("# ").strip() in STOP_HEADINGS:
                return units, section, True
            numbered = re.match(r"(\d+\.\d+)\s", text)
            if numbered:
                # Running headers ("5.3 • Newton's Second Law") name the same section as the outline does.
                section = canonical.get(numbered.group(1), text)
            else:
                pending.append(_block_markdown(block))
            continue
        if block["type"] == "figure":
            flush()
            figures += 1
            box = _figure_box(block.get("box"), images)
            crop = _crop(image_path, box, asset_dir / f"p{page_number:04d}_fig{figures}.jpg", source_id) if box else asset
            units.append({
                "id": f"{source_id}:p{page_number}:fig{figures}",
                "source_id": source_id,
                "kind": "figure",
                "modality": "vision",
                "locator": {"page": page_number, "label": block.get("label", ""), **({"rect": box} if box else {})},
                "section": section,
                "text": text,
                "asset": crop,
            })
            continue
        piece = _block_markdown(block)
        pending.append(piece)
        words += len(piece.split())
        following = blocks[position + 1]["type"] if position + 1 < len(blocks) else None
        # Keep a displayed equation with the sentence that introduces it.
        if words >= TARGET_WORDS and following != "equation" and not text.rstrip().endswith((":", ",")):
            flush()
    flush()
    return units, section, False


def _paragraphs(text: str) -> list[str]:
    """Rough paragraphs from a text layer: lines joined until one ends a sentence and the next starts one."""
    paragraphs, current = [], []
    for line in (l.strip() for l in text.splitlines()):
        if not line:
            continue
        current.append(line)
        if line.endswith((".", "?", "!", ":")) and sum(len(c.split()) for c in current) >= 60:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def _crop(page_image: Path, box: list[float], target: Path, source_id: str) -> str:
    from PIL import Image

    if not target.exists():
        with Image.open(page_image) as image:
            width, height = image.size
            pad = 0.01
            region = (
                int(max(0.0, box[0] - pad) * width),
                int(max(0.0, box[1] - pad) * height),
                int(min(1.0, box[2] + pad) * width),
                int(min(1.0, box[3] + pad) * height),
            )
            image.crop(region).save(target, quality=85)
    return f"{source_id}/{target.name}"
