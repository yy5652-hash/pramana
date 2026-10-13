"""Type with formulas in it, for the cards of a lesson film.

Question stems and answers hold inline LaTeX ($a = \\frac{F}{m}$). The film is drawn with Pillow,
which knows nothing of TeX, and the app's KaTeX runs only in a browser. This module sets the
small part of LaTeX the question bank uses, with the KaTeX fonts the app already ships:
letters in the math italic, fractions stacked, scripts raised and lowered, arrows and bars drawn
over their letter. A command it does not know is shown by its name, never dropped.

    laid = layout("Find $a$ if $F_{\\text{net}} = 12\\ \\text{N}$ and $m = 3\\ \\text{kg}$.", 34, CHALK, 900)
    laid.paint(pen, x, y)          # y is the top of the first line; laid.height is what it took
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from PIL import ImageDraw, ImageFont

from ..config import ROOT

_FONT_DIR = ROOT / "web" / "vendor" / "katex" / "fonts"
_FILES = {"roman": "KaTeX_Main-Regular.woff2", "bold": "KaTeX_Main-Bold.woff2", "italic": "KaTeX_Math-Italic.woff2",
          "big": "KaTeX_Size1-Regular.woff2", "ams": "KaTeX_AMS-Regular.woff2", "mono": "KaTeX_Typewriter-Regular.woff2", "sans": "KaTeX_SansSerif-Regular.woff2"}

Colour = tuple[int, int, int]


@lru_cache(maxsize=128)
def face(kind: str, size: int) -> ImageFont.FreeTypeFont:
    path = _FONT_DIR / _FILES[kind]
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default(size)


@lru_cache(maxsize=2048)
def _has(kind: str, char: str) -> bool:
    """Whether a font really holds a glyph (a missing one is drawn as the same empty box every time)."""
    probe = face(kind, 40)
    if not isinstance(probe, ImageFont.FreeTypeFont):
        return char.isascii()
    return bytes(probe.getmask(char)) != bytes(probe.getmask("￿")) or char.isspace()


@dataclass
class Box:
    """A piece of set type: how wide it is, how far it reaches above and below the baseline, and how to draw itself."""
    width: float
    up: float
    down: float
    paint: Callable[[ImageDraw.ImageDraw, float, float], None]      # pen, left edge, baseline


def _nothing(*_) -> None:
    return None


def space(width: float) -> Box:
    return Box(width, 0, 0, _nothing)


def glyphs(text: str, kind: str, size: float, colour: Colour) -> Box:
    """A run of characters in one font; a character the font lacks falls back to the roman, then to Pillow's own."""
    if not text:
        return space(0)
    if any(not _has(kind, c) for c in text) and len(text) > 1:
        return row([glyphs(c, kind, size, colour) for c in text])
    if not _has(kind, text[0]):
        kind = next((k for k in ("roman", "ams", "big", "italic") if _has(k, text[0])), kind)
    font = face(kind, max(int(round(size)), 6)) if _has(kind, text[0]) else ImageFont.load_default(max(int(round(size * 0.9)), 6))
    left, top, right, bottom = font.getbbox(text, anchor="ls")
    return Box(font.getlength(text), max(-top, 0), max(bottom, 0), lambda pen, x, y: pen.text((x, y), text, font=font, fill=colour, anchor="ls"))


def row(boxes: list[Box]) -> Box:
    boxes = [b for b in boxes if b is not None]
    if len(boxes) == 1:
        return boxes[0]

    def paint(pen, x, y):
        for box in boxes:
            box.paint(pen, x, y)
            x += box.width

    return Box(sum(b.width for b in boxes), max((b.up for b in boxes), default=0), max((b.down for b in boxes), default=0), paint)


def lifted(box: Box, by: float) -> Box:
    """The same box with its baseline moved up by `by` (down when negative)."""
    return Box(box.width, box.up + by, box.down - by, lambda pen, x, y: box.paint(pen, x, y - by))


def scripts(base: Box, sup: Box | None, sub: Box | None, size: float) -> Box:
    parts, tail = [base], []
    if sup:
        tail.append(lifted(sup, max(0.42 * size, base.up - 0.55 * sup.up)))
    if sub:
        tail.append(lifted(sub, -max(0.2 * size, base.down + 0.1 * size)))
    width = max(b.width for b in tail)

    def paint(pen, x, y):
        base.paint(pen, x, y)
        for box in tail:
            box.paint(pen, x + base.width + 0.03 * size, y)

    return Box(base.width + width + 0.06 * size, max([base.up] + [b.up for b in tail]), max([base.down] + [b.down for b in tail]), paint)


def fraction(top: Box, bottom: Box, size: float, colour: Colour) -> Box:
    axis, gap, rule, pad = 0.27 * size, 0.13 * size, max(1, round(0.045 * size)), 0.12 * size
    width = max(top.width, bottom.width) + 2 * pad

    def paint(pen, x, y):
        line = y - axis
        pen.line((x + pad * 0.4, line, x + width - pad * 0.4, line), fill=colour, width=rule)
        top.paint(pen, x + (width - top.width) / 2, line - gap - top.down)
        bottom.paint(pen, x + (width - bottom.width) / 2, line + gap + rule + bottom.up)

    return Box(width + 0.08 * size, axis + gap + top.up + top.down, gap + rule + bottom.up + bottom.down - axis, paint)


def accent(base: Box, kind: str, size: float, colour: Colour) -> Box:
    """A letter with an arrow, a bar or a hat drawn over it."""
    gap, stroke = 0.1 * size, max(1, round(0.045 * size))
    rise = 0.16 * size if kind != "bar" else 0.06 * size

    def paint(pen, x, y):
        base.paint(pen, x, y)
        top = y - base.up - gap
        a, b = x + 0.08 * base.width, x + max(base.width, 0.5 * size) * 0.98
        if kind == "bar":
            pen.line((a, top, b, top), fill=colour, width=stroke)
        elif kind == "hat":
            mid = (a + b) / 2
            pen.line((mid - 0.2 * size, top, mid, top - rise, mid + 0.2 * size, top), fill=colour, width=stroke, joint="curve")
        else:
            head = 0.17 * size
            pen.line((a, top - rise / 2, b, top - rise / 2), fill=colour, width=stroke)
            pen.line((b - head, top - rise / 2 - head * 0.6, b, top - rise / 2, b - head, top - rise / 2 + head * 0.6), fill=colour, width=stroke, joint="curve")

    return Box(max(base.width, 0.5 * size), base.up + gap + rise + stroke, base.down, paint)


def radical(inner: Box, size: float, colour: Colour) -> Box:
    gap, stroke, lead = 0.1 * size, max(1, round(0.05 * size)), 0.5 * size

    def paint(pen, x, y):
        top, foot = y - inner.up - gap, y + inner.down
        pen.line((x, y - 0.3 * size, x + lead * 0.3, y - 0.36 * size, x + lead * 0.58, foot, x + lead * 0.9, top, x + lead + inner.width + 0.08 * size, top),
                 fill=colour, width=stroke, joint="curve")
        inner.paint(pen, x + lead, y)

    return Box(lead + inner.width + 0.12 * size, inner.up + gap + stroke, inner.down, paint)


# ---- the part of LaTeX the question bank uses ------------------------------------------------

_SYMBOL = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ϵ", "theta": "θ", "lambda": "λ", "mu": "μ", "pi": "π", "rho": "ρ",
    "sigma": "σ", "tau": "τ", "phi": "ϕ", "omega": "ω", "Delta": "Δ", "Sigma": "Σ", "Omega": "Ω", "Theta": "Θ", "Phi": "Φ",
    "times": "×", "cdot": "·", "approx": "≈", "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠", "pm": "±", "circ": "∘",
    "infty": "∞", "rightarrow": "→", "to": "→", "Rightarrow": "⇒", "propto": "∝", "bot": "⊥", "perp": "⊥", "parallel": "∥", "angle": "∠",
    "partial": "∂", "nabla": "∇", "fallingdotseq": "≈", "sim": "∼", "ll": "≪", "gg": "≫", "degree": "°", "prime": "′", "ell": "ℓ",
}
_FUNCTION = {"sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan", "ln", "log", "exp", "max", "min", "lim"}
_SPACE = {" ": 0.28, ",": 0.17, ";": 0.28, ":": 0.22, "!": -0.1, "quad": 1.0, "qquad": 2.0}
_RELATION = set("=<>≈≤≥≠∝→⇒+−×·±")
_TOKEN = re.compile(r"\\[a-zA-Z]+|\\.|[{}^_]|\s+|.", re.S)


class _Math:
    def __init__(self, tex: str, colour: Colour):
        self.tokens, self.i, self.colour = _TOKEN.findall(tex), 0, colour

    def _peek(self) -> str | None:
        while self.i < len(self.tokens) and self.tokens[self.i].isspace():
            self.i += 1
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def row(self, size: float, cramped: bool = False) -> Box:
        items: list[Box] = []
        while (token := self._peek()) is not None and token != "}":
            self.i += 1
            if token in "^_":
                base = items.pop() if items else space(0)
                marks = {token: self.argument(size * 0.7, True)}
                if (other := self._peek()) in ("^", "_") and other not in marks:
                    self.i += 1
                    marks[other] = self.argument(size * 0.7, True)
                items.append(scripts(base, marks.get("^"), marks.get("_"), size))
            else:
                items.append(self.atom(token, size, cramped))
        return row(items) if items else space(0)

    def argument(self, size: float, cramped: bool = False) -> Box:
        token = self._peek()
        if token is None:
            return space(0)
        self.i += 1
        if token == "{":
            box = self.row(size, cramped)
            if self._peek() == "}":
                self.i += 1
            return box
        return self.atom(token, size, cramped)

    def _raw_group(self) -> str:
        """The text of the next {group}, spaces kept: what \\text{ kg} holds."""
        if self.i >= len(self.tokens) or self.tokens[self.i] != "{":
            return ""
        depth, out, self.i = 1, [], self.i + 1
        while self.i < len(self.tokens):
            token = self.tokens[self.i]
            self.i += 1
            depth += (token == "{") - (token == "}")
            if depth == 0:
                break
            out.append(token)
        return "".join(out)

    def atom(self, token: str, size: float, cramped: bool) -> Box:
        colour = self.colour
        if token == "{":
            box = self.row(size, cramped)
            if self._peek() == "}":
                self.i += 1
            return box
        if not token.startswith("\\"):
            if token.isalpha():
                return glyphs(token, "italic", size, colour)
            char = {"-": "−", "*": "·", "'": "′"}.get(token, token)
            if char in _RELATION and not cramped:
                return row([space(0.2 * size), glyphs(char, "roman", size, colour), space(0.2 * size)])
            return glyphs(char, "roman", size, colour)
        name = token[1:]
        if name in ("text", "mathrm", "textrm", "operatorname", "textit", "mathit"):
            words = self._raw_group().replace("\\ ", " ").replace("\\", "")
            return glyphs(re.sub(r"\s+", " ", words), "roman", size, colour)
        if name in ("mathbf", "textbf", "boldsymbol", "bm"):
            return glyphs(self._raw_group().replace("\\", ""), "bold", size, colour)
        if name in ("frac", "dfrac", "tfrac"):
            inner = size * (0.78 if not cramped else 0.72)
            top = self.argument(inner, cramped)
            return fraction(top, self.argument(inner, cramped), size, colour)
        if name in ("vec", "bar", "overline", "hat"):
            return accent(self.argument(size, cramped), {"overline": "bar"}.get(name, name), size, colour)
        if name == "sqrt":
            return radical(self.argument(size, cramped), size, colour)
        if name in ("left", "right", "big", "Big", "bigg"):
            if self.i < len(self.tokens):
                mark = self.tokens[self.i]
                self.i += 1
                mark = {"\\{": "{", "\\}": "}", "\\|": "‖", ".": ""}.get(mark, mark)
                return glyphs(mark, "roman", size, colour) if mark else space(0)
            return space(0)
        if name in ("sum", "int", "prod"):
            return row([glyphs({"sum": "∑", "int": "∫", "prod": "∏"}[name], "big", size, colour), space(0.12 * size)])
        if name in _FUNCTION:
            return row([space(0.12 * size), glyphs(name, "roman", size, colour), space(0.14 * size)])
        if name in _SPACE:
            return space(_SPACE[name] * size)
        if name in ("ne", "neq"):                                   # the fonts build this sign from two; so does this
            equals = glyphs("=", "roman", size, colour)

            def struck(pen, x, y, equals=equals):
                equals.paint(pen, x, y)
                pen.line((x + 0.2 * equals.width, y + 0.08 * size, x + 0.8 * equals.width, y - 0.62 * size), fill=colour, width=max(1, round(0.05 * size)))

            return row([space(0.2 * size), Box(equals.width, 0.66 * size, 0.1 * size, struck), space(0.2 * size)])
        if name in _SYMBOL:
            char = _SYMBOL[name]
            box = glyphs(char, "italic" if char.isalpha() and char.islower() else "roman", size, colour)
            return row([space(0.2 * size), box, space(0.2 * size)]) if char in _RELATION and not cramped else box
        if len(name) == 1:                                          # an escaped character: \%, \$, \#
            return glyphs(name, "roman", size, colour)
        return glyphs(name, "roman", size, colour)                    # an unknown command keeps its name


def formula(tex: str, size: float, colour: Colour) -> Box:
    """One inline formula as a box."""
    return _Math(tex, colour).row(size)


# ---- paragraphs -----------------------------------------------------------------------------

_INLINE = re.compile(r"\$\$?(.+?)\$\$?", re.S)
# Characters the shipped fonts do not hold, written the way they do.
_PLAIN = {"½": "1/2", "¼": "1/4", "¾": "3/4", "²": "$^{2}$", "³": "$^{3}$", "•": "·", "≠": "$\\neq$", "″": "′′", "✓": "", "✗": ""}


def unit(text: str) -> str:
    """A unit as LaTeX: "m/s^2" becomes \\text{m/s}^{2}; a unit that is not one ("dimensionless") becomes nothing."""
    text = (text or "").strip()
    if not text or text.lower() in ("dimensionless", "none", "unitless"):
        return ""
    if text.lower() in ("degrees", "degree", "deg"):
        return "^{\\circ}"
    return re.sub(r"([^\^]+)(?:\^\{?(-?\d+)\}?)?", lambda m: f"\\text{{{m.group(1)}}}" + (f"^{{{m.group(2)}}}" if m.group(2) else ""), text)


@dataclass
class Laid:
    lines: list[tuple[list[Box], float, float]]        # the boxes of a line, and how far it reaches above and below its baseline
    width: float
    height: float
    gap: float

    def paint(self, pen: ImageDraw.ImageDraw, x: float, y: float, centre: float | None = None) -> None:
        for boxes, up, down in self.lines:
            cursor = x + ((centre - sum(b.width for b in boxes)) / 2 if centre else 0)
            for box in boxes:
                box.paint(pen, cursor, y + up)
                cursor += box.width
            y += up + down + self.gap


def layout(text: str, size: float, colour: Colour, width: float, kind: str = "roman", leading: float = 1.34) -> Laid:
    """Set a paragraph that may hold $formulas$, broken into lines no wider than `width`.

    A line is as tall as the type it holds: a line with a fraction in it takes more room, and
    the ones around it keep the ordinary spacing.
    """
    words: list[Box] = []
    text = re.sub(r"\*\*(.+?)\*\*|`(.+?)`", lambda m: m.group(1) or m.group(2), text or "")
    for char, written in _PLAIN.items():
        text = text.replace(char, written)
    pieces, at = [], 0
    for match in _INLINE.finditer(text):
        pieces += [(False, text[at: match.start()]), (True, match.group(1))]
        at = match.end()
    pieces.append((False, text[at:]))
    current: list[Box] = []
    for is_math, piece in pieces:
        if is_math:
            box, smaller = formula(piece, size, colour), size
            while box.width > width and smaller > 8:                # a formula longer than the line is set smaller, never cut
                smaller *= min(width / box.width, 0.98) * 0.99
                box = formula(piece, smaller, colour)
            current.append(box)
            continue
        for part in re.split(r"(\s+)", piece):
            if not part:
                continue
            if part.isspace():
                if current:
                    words.append(row(current))
                    current = []
            else:
                current.append(glyphs(part, kind, size, colour))
    if current:
        words.append(row(current))

    gap_word = face(kind, max(int(size), 6)).getlength(" ") if isinstance(face(kind, max(int(size), 6)), ImageFont.FreeTypeFont) else size * 0.3
    plain_up, plain_down = 0.76 * size, 0.24 * size
    lines, line, used = [], [], 0.0
    for word in words:
        extra = word.width + (gap_word if line else 0)
        if line and used + extra > width:
            lines.append(line)
            line, used, extra = [], 0.0, word.width
        if line:
            line.append(space(gap_word))
        line.append(word)
        used += extra
    if line:
        lines.append(line)
    laid = [(boxes, max([plain_up] + [b.up for b in boxes]), max([plain_down] + [b.down for b in boxes])) for boxes in lines]
    gap = (leading - 1) * size
    height = sum(up + down for _, up, down in laid) + gap * max(len(laid) - 1, 0)
    return Laid(laid, max((sum(b.width for b in boxes) for boxes, _, _ in laid), default=0.0), height, gap)


def spoken(text: str) -> str:
    """The same text with its formulas taken out, for places that need plain words (a caption, a log line)."""
    return re.sub(r"\s+", " ", _INLINE.sub(" ", text or "")).strip()
