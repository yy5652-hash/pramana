"""Vision-language reading of pages, slides and video frames.

Why this exists: in many textbooks (the OpenStax PDFs among them) every equation and symbol
is drawn as graphics, so the PDF text layer reads "the average and instantaneous
accelerations are equal—that is," and then nothing. Figures carry no text at all. A tutor
built on the text layer alone cannot quote a single formula. The model below restores the
maths as LaTeX and writes a description of each figure, with a bounding box so a citation can
show the figure itself.
"""
from __future__ import annotations

from pathlib import Path

from ..config import settings
from ..llm import LLMResult, image_part, llm, repair_maths

# Cached replies are keyed on (prompt version, source file hash, position), never on image
# bytes. Bump a version when its prompt changes.
PAGE_PROMPT_VERSION = "page-v1"
SLIDE_PROMPT_VERSION = "slide-v1"
FRAME_PROMPT_VERSION = "frame-v1"

PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["heading", "paragraph", "equation", "figure", "table", "example", "list"],
                    },
                    "text": {"type": "string"},
                    "label": {"type": "string"},
                    "box": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["type", "text"],
            },
        }
    },
    "required": ["blocks"],
}

PAGE_PROMPT = """You are transcribing one page of a textbook for a study tool. Students will be shown this transcription next to the page, so it must be faithful.

Return the page as an ordered list of blocks:
- heading: section or subsection titles.
- paragraph: body text. Write inline maths as LaTeX between $...$. The page's text layer is given below; it is accurate for words but may have every equation and symbol missing. Use the image to restore them.
- equation: a displayed equation, as LaTeX only (no $ delimiters). Put its equation number, if any, in "label".
- figure: one block per figure. "label" is the figure number (e.g. "Figure 5.10"). "text" is the caption followed by " — " and a precise description of what the figure shows: objects, axes and their units, vectors and their directions, labelled values, and what a student should read off it. "box" is the figure's bounding box as [ymin, xmin, ymax, xmax] on a 0-1000 scale.
- table: the table as Markdown. example: a worked example's statement and solution, with maths in LaTeX. list: bullet or numbered lists.

Rules: keep reading order; copy wording exactly; do not summarise, explain, or add anything that is not on the page; skip running headers, footers and page numbers.

Text layer:
"""

SLIDE_SCHEMA = {
    "type": "object",
    "properties": {
        "has_visual": {"type": "boolean"},
        "description": {"type": "string"},
        "equations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["has_visual", "description", "equations"],
}

SLIDE_PROMPT = """This is a lecture slide. Its extracted text is given below, but equations and pictures are missing from that text.

- "equations": every equation or formula visible on the slide, as LaTeX, in reading order.
- "description": if the slide has a diagram, graph or photo, describe it for a student who cannot see it: what is drawn, axes and units, vectors and their directions, labelled values, and the point it makes. Leave empty if there is none.
- "has_visual": true only if there is a diagram, graph or photo that carries meaning. Logos and decoration do not count.

Report only what is visible on the slide; do not add outside facts.

Slide text:
"""

FRAME_SCHEMA = {
    "type": "object",
    "properties": {
        "has_content": {"type": "boolean"},
        "board": {"type": "string"},
        "equations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["has_content", "board", "equations"],
}

FRAME_PROMPT = """This is a frame from a lecture video. The instructor writes and draws on a board. What they said during this part of the lecture is given below to help you read the handwriting.

Report what is on the board at this moment: in "board", describe diagrams, axes, vectors and labels in one or two sentences; in "equations", list every written equation or expression as LaTeX, in the order written. Report only what is visible in the frame, not what is said. If nothing is written or drawn yet, set has_content to false.

Spoken during this segment:
"""


def _see(prompt: str, image: Path, namespace: str, schema: dict, cache_key: list) -> LLMResult:
    return llm().chat(
        [{"role": "user", "content": [{"type": "text", "text": prompt}, image_part(image)]}],
        models=settings.vision_models,
        namespace=namespace,
        schema=schema,
        cache_key=cache_key,
    )


def read_page(image: Path, text_layer: str, cache_key: list) -> tuple[list[dict], LLMResult]:
    result = _see(PAGE_PROMPT + text_layer, image, "ingest-pages", PAGE_SCHEMA, cache_key)
    blocks = [b for b in result.json().get("blocks", []) if b.get("text", "").strip()]
    for block in blocks:
        if block.get("type") == "equation":
            block["text"] = repair_maths(block["text"])
    return blocks, result


def _with_equations(reply: dict) -> dict:
    reply["equations"] = [repair_maths(e) for e in reply.get("equations", []) if isinstance(e, str)]
    return reply


def read_slide(image: Path, slide_text: str, cache_key: list) -> dict:
    return _with_equations(_see(SLIDE_PROMPT + slide_text, image, "ingest-slides", SLIDE_SCHEMA, cache_key).json())


def read_frame(image: Path, spoken: str, cache_key: list) -> dict:
    return _with_equations(_see(FRAME_PROMPT + spoken, image, "ingest-frames", FRAME_SCHEMA, cache_key).json())
