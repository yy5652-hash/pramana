"""Cuts the film of a lesson. Pure Python: Pillow draws the frames, PyAV encodes them.

A lesson is a list of shots. Each shot knows how long it is, what it sounds like, how to draw
itself at time t, where its picture comes from (the tag in the corner) and what is being said
(the caption). Three kinds of picture exist, and all three are the course's own material:

* a still (a textbook page or a slide) with a camera that moves over it, the cited passage
  outlined and the quoted words lit;
* a clip of a lecture video, either under the narrator or with the lecturer's own voice;
* a card of type, for the title and the ending.

Nothing is generated: every pixel of a still or a clip is a source the student uploaded.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFont

from ..config import ROOT
from . import typeset

W, H, FPS = 1280, 720, 30
RATE = 48000                    # audio sample rate of the finished film
BLACK, CHALK, DIM, FAINT, CITE = (5, 5, 5), (243, 239, 230), (150, 145, 135), (84, 80, 73), (240, 138, 42)
GOOD, BAD = (136, 198, 142), (236, 116, 98)       # the right answer and the wrong one, on a card
FADE = 7                        # frames a shot takes to come up from black and to go back

_FONT_DIR = ROOT / "web" / "vendor" / "katex" / "fonts"
_FONT_FILES = {"serif": "KaTeX_Main-Regular.woff2", "bold": "KaTeX_Main-Bold.woff2", "mono": "KaTeX_Typewriter-Regular.woff2"}


@lru_cache(maxsize=64)
def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    """Type for the film. The serif and the mono are the KaTeX fonts the web app already ships;
    captions use Pillow's own sans, which covers every Latin character a caption may hold."""
    name = _FONT_FILES.get(kind)
    if name and (_FONT_DIR / name).exists():
        try:
            return ImageFont.truetype(str(_FONT_DIR / name), size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def ease(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def wrap(text: str, face: ImageFont.FreeTypeFont, width: float) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and face.getlength(trial) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + [line] if line else lines


@dataclass
class Shot:
    seconds: float
    draw: Callable[[float], Image.Image]                 # time in the shot -> an RGB frame, W x H, free to be drawn on
    audio: np.ndarray                                     # mono float32 at RATE; padded or cut to the shot's length
    tag: str = ""                                         # where the picture is from
    number: int | None = None                             # the citation number of that source
    captions: list[tuple[float, float, str]] = field(default_factory=list)


# ---- stills ---------------------------------------------------------------------------------

class Still:
    """A page or a slide lying on a black table, and a camera that frames part of it."""

    def __init__(self, picture: Image.Image):
        self.margin = max(picture.size) // 2 + 8
        self.table = Image.new("RGB", (picture.width + 2 * self.margin, picture.height + 2 * self.margin), BLACK)
        self.table.paste(picture, (self.margin, self.margin))

    def view(self, box: tuple[float, float, float, float]) -> Image.Image:
        m = self.margin
        return self.table.resize((W, H), Image.Resampling.BICUBIC, box=(box[0] + m, box[1] + m, box[2] + m, box[3] + m))


def window(cx: float, cy: float, width: float) -> tuple[float, float, float, float]:
    """The 16:9 rectangle of a given width centred on a point."""
    height = width * H / W
    return (cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2)


def between(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def marked(page: Image.Image, passage: tuple[float, float, float, float], quote: list[tuple[float, float, float, float]]) -> tuple[Image.Image, Image.Image]:
    """The page with the cited passage picked out, and the same with the quoted words lit.

    The rest of the page is dimmed, not hidden: the reader can still see where on the page
    the passage sits.
    """
    scale = page.width / 1000
    pad = 10 * scale
    box = tuple(int(v) for v in (max(passage[0] - pad, 0), max(passage[1] - pad, 0), min(passage[2] + pad, page.width), min(passage[3] + pad, page.height)))
    plain = ImageEnhance.Brightness(page).enhance(0.42)
    plain.paste(page.crop(box), box[:2])
    ImageDraw.Draw(plain).rounded_rectangle(box, radius=int(9 * scale), outline=CITE, width=max(2, int(3.2 * scale)))
    lit = plain.copy()
    for rect in quote:
        area = tuple(int(v) for v in (rect[0] - 2 * scale, rect[1] - 2 * scale, rect[2] + 2 * scale, rect[3] + 2 * scale))
        if area[2] > area[0] and area[3] > area[1]:
            lit.paste(ImageChops.multiply(lit.crop(area), Image.new("RGB", (area[2] - area[0], area[3] - area[1]), (255, 214, 150))), area[:2])
    return plain, lit


def read_shot(page: Image.Image, passage: tuple[float, float, float, float], quote: list[tuple[float, float, float, float]], seconds: float) -> Callable[[float], Image.Image]:
    """A camera reading a passage on a page: it arrives, the quoted words light up, and it either
    pushes in slowly or, when the passage is taller than the frame, travels down it."""
    plain, lit = (Still(image) for image in marked(page, passage, quote))
    cx = (passage[0] + passage[2]) / 2
    width = min(max((passage[2] - passage[0]) / 0.86, page.width * 0.6), page.width * 1.05)
    height = width * H / W
    # The passage is kept in the band of the frame between the source tag and the captions.
    clear_top, clear_bottom = 0.15, 0.76
    room, shift = (clear_bottom - clear_top) * height, (0.5 - (clear_top + clear_bottom) / 2) * height
    top, bottom = passage[1], passage[3]
    if bottom - top <= room:
        start = window(cx, (top + bottom) / 2 + shift, width * 1.07)
        end = window(cx, (top + bottom) / 2 + shift, width)
    else:
        first, last = top + room / 2 + shift, bottom - room / 2 + shift
        aim = (min(r[1] for r in quote) + max(r[3] for r in quote)) / 2 + shift if quote else last
        start, end = window(cx, first, width), window(cx, min(max(aim, first), last), width)
    light_at = 0.9 if quote else None

    def draw(t: float) -> Image.Image:
        box = between(start, end, ease(t / max(seconds - 0.4, 0.1)))
        if light_at is None or t <= light_at:
            return plain.view(box)
        frame = lit.view(box)
        glow = (t - light_at) / 0.35
        return frame if glow >= 1 else Image.blend(plain.view(box), frame, glow)

    return draw


def slide_shot(slide: Image.Image, seconds: float) -> Callable[[float], Image.Image]:
    """A slide shown whole, between the source tag and the captions, then leaned into a little."""
    still = Still(slide)
    cx = slide.width / 2
    tall = slide.height / 0.72                              # the slide takes 72 % of the frame's height,
    start = window(cx, 0.385 * tall, tall * W / H)          # starts just below the tag
    end = window(cx, 0.388 * tall, tall * 0.975 * W / H)    # and ends above where the captions sit
    return lambda t: still.view(between(start, end, ease(t / max(seconds, 0.1))))


# ---- lecture video --------------------------------------------------------------------------

class Clip:
    """Frames of a lecture video from a start time on, decoded as they are asked for."""

    def __init__(self, path: Path, start: float, length: float):
        import av

        self.container = av.open(str(path))
        self.stream = self.container.streams.video[0]
        self.start, self.length = start, length
        self.container.seek(int(max(start - 1.5, 0) / self.stream.time_base), stream=self.stream, backward=True)
        self.frames = self.container.decode(self.stream)
        self.current: Image.Image | None = None
        self.time = -1.0

    def frame(self, t: float) -> Image.Image:
        wanted = self.start + min(max(t, 0.0), self.length)       # past the end, the last frame holds
        while self.time < wanted:
            try:
                decoded = next(self.frames)
            except StopIteration:
                break
            if decoded.time is None:
                continue
            self.time = decoded.time
            if self.time >= self.start - 0.05 or self.current is None:
                self.current = decoded.to_image()
        if self.current is None:
            return Image.new("RGB", (W, H), BLACK)
        return self.current.convert("RGB").resize((W, H), Image.Resampling.BICUBIC)


def clip_audio(path: Path, start: float, length: float) -> np.ndarray:
    """The sound of a stretch of video, mono at RATE, brought to a speaking level."""
    import av

    pieces = []
    with av.open(str(path)) as container:
        if not container.streams.audio:
            return np.zeros(int(length * RATE), dtype=np.float32)
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="flt", layout="mono", rate=RATE)
        container.seek(int(max(start - 0.5, 0) / stream.time_base), stream=stream, backward=True)
        first = None
        for frame in container.decode(stream):
            if frame.time is None or frame.time + 0.1 < start - 0.5:
                continue
            if frame.time > start + length + 0.5:
                break
            if first is None:
                first = frame.time
            for out in resampler.resample(frame):
                pieces.append(out.to_ndarray().reshape(-1))
    if not pieces:
        return np.zeros(int(length * RATE), dtype=np.float32)
    samples = np.concatenate(pieces).astype(np.float32)
    samples = samples[max(int((start - first) * RATE), 0):][: int(length * RATE)]
    level = float(np.sqrt(np.mean(samples ** 2))) if len(samples) else 0.0
    if level > 1e-5:
        samples = np.clip(samples * min(0.11 / level, 8.0), -0.95, 0.95)       # lecture recordings are quiet; lift them to the narrator's level
    edge = min(RATE // 25, len(samples) // 2)
    if edge:
        samples[:edge] *= np.linspace(0, 1, edge)
        samples[-edge:] *= np.linspace(1, 0, edge)
    return samples


# ---- cards ----------------------------------------------------------------------------------

def card(lines: list[tuple[str, str, int, tuple[int, int, int]]], top: int = 0, gap: int = 18, rule: int | None = None) -> Callable[[float], Image.Image]:
    """A card of type on the black stage. Each line is (text, font kind, size, colour); long lines wrap."""
    image = Image.new("RGB", (W, H), BLACK)
    pen = ImageDraw.Draw(image)
    laid = []
    for text, kind, size, colour in lines:
        face = font(kind, size)
        for line in wrap(text, face, W - 240) or [""]:
            laid.append((line, face, int(size * 1.28), colour))
    y = top or (H - sum(h for _, _, h, _ in laid) - gap * (len(laid) - 1)) // 2
    for index, (line, face, height, colour) in enumerate(laid):
        pen.text((120, y), line, font=face, fill=colour)
        if rule is not None and index == rule:
            pen.line((120, y + height + gap // 2, 120 + 150, y + height + gap // 2), fill=CITE, width=3)
            y += gap
        y += height + gap
    return lambda t: image.copy()


def panel(blocks: list[dict], top: int = 104, bottom: int = 560, left: int = 120, width: int = W - 240) -> Callable[[float], Image.Image]:
    """A card of set type, formulas included, that builds up as it is spoken.

    Each block is a paragraph: "text" (which may hold $formulas$), "size", "colour", "face", and
    optionally "lead" (a small label in a column to its left, such as YOU ANSWERED), "badge" (the
    citation number it rests on), "above" (extra room over it) and "at" (the second it appears).
    The blocks sit between the source tag and the captions; if they do not fit, all are set smaller.
    """
    for scale in (1.0, 0.92, 0.85, 0.78, 0.72, 0.66, 0.6, 0.54):
        column = max([typeset.glyphs(b["lead"], "mono", b.get("size", 30) * b.get("lead_size", 0.6) * scale, DIM).width for b in blocks if b.get("lead")] + [0.0])
        column = column + 26 * scale if column else 0.0
        laid, y = [], 0.0
        for block in blocks:
            size = block.get("size", 30) * scale
            badge = 46 * scale if block.get("badge") is not None else 0.0
            indent = column if block.get("lead") else 0.0
            text = typeset.layout(block["text"], size, block.get("colour", CHALK), width - indent - badge, block.get("face", "roman"))
            y += block.get("above", 0) * scale
            laid.append((block, text, y, size, badge, indent))
            y += text.height + 0.5 * size
        if y <= bottom - top or scale == 0.54:
            break
    start = top + max((bottom - top - y) / 2, 0)
    stages = sorted({round(float(block.get("at", 0.0)), 2) for block in blocks})
    images = []
    for stage in stages:
        image = Image.new("RGB", (W, H), BLACK)
        pen = ImageDraw.Draw(image)
        for block, text, offset, size, badge, indent in laid:
            if block.get("at", 0.0) > stage + 1e-6:
                continue
            line_up = text.lines[0][1] if text.lines else size * 0.76
            if block.get("lead"):
                typeset.glyphs(block["lead"], "mono", size * block.get("lead_size", 0.6), block.get("lead_colour", DIM)).paint(pen, left, start + offset + line_up)
            if badge:
                box = (left + indent, start + offset + line_up - 0.78 * size, left + indent + 32 * scale, start + offset + line_up + 0.14 * size)
                pen.rounded_rectangle(box, radius=7 * scale, fill=CITE)
                pen.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), str(block["badge"]), font=font("bold", int(size * 0.72)), fill=(20, 12, 4), anchor="mm")
            text.paint(pen, left + indent + badge, start + offset)
            if block.get("rule"):
                under = start + offset + text.height + 0.32 * size
                pen.line((left, under, left + 150, under), fill=CITE, width=3)
        images.append(image)

    def draw(t: float) -> Image.Image:
        k = bisect.bisect_right(stages, t) - 1
        if k <= 0:
            return images[0].copy()
        glow = (t - stages[k]) / 0.3
        return images[k].copy() if glow >= 1 else Image.blend(images[k - 1], images[k], max(glow, 0.0))

    return draw


# ---- what lies over every shot --------------------------------------------------------------

def _plate(text: str, face: ImageFont.FreeTypeFont, colour: tuple, pad: tuple[int, int], width: int | None = None, badge: int | None = None) -> Image.Image:
    lines = wrap(text, face, width) if width else [text]
    line_h = int(face.size * 1.32)
    text_w = int(max(face.getlength(line) for line in lines))
    lead = 44 if badge is not None else 0
    plate = Image.new("RGBA", (text_w + 2 * pad[0] + lead, line_h * len(lines) + 2 * pad[1]), (0, 0, 0, 0))
    pen = ImageDraw.Draw(plate)
    pen.rounded_rectangle((0, 0, plate.width - 1, plate.height - 1), radius=12, fill=(6, 6, 6, 218))
    if badge is not None:
        pen.rounded_rectangle((pad[0], pad[1] + 1, pad[0] + 30, pad[1] + line_h - 3), radius=7, fill=CITE + (255,))
        number = font("bold", int(face.size * 0.95))
        pen.text((pad[0] + 15, pad[1] + line_h / 2 - 1), str(badge), font=number, fill=(20, 12, 4, 255), anchor="mm")
    for i, line in enumerate(lines):
        x = pad[0] + lead + (text_w - face.getlength(line)) / 2 * (1 if width else 0)
        pen.text((x, pad[1] + i * line_h), line, font=face, fill=colour + (255,))
    return plate


def split_caption(text: str, seconds: float, lead: float = 0.0, words: int = 13) -> list[tuple[float, float, str]]:
    """Cut a narration line into caption-sized pieces and time them by their share of the letters."""
    tokens, pieces, piece = text.split(), [], []
    for token in tokens:
        piece.append(token)
        if len(piece) >= words or (len(piece) >= 6 and token[-1] in ".,;:?!"):
            pieces.append(" ".join(piece))
            piece = []
    if piece:
        if pieces and len(piece) < 3:
            pieces[-1] += " " + " ".join(piece)
        else:
            pieces.append(" ".join(piece))
    total = sum(len(p) for p in pieces) or 1
    out, clock = [], lead
    for p in pieces:
        span = seconds * len(p) / total
        out.append((round(clock, 2), round(clock + span, 2), p))
        clock += span
    return out


def render(shots: list[Shot], path: Path, progress: Callable[[float], None] = lambda _: None) -> float:
    """Encode the shots to an MP4 (H.264 + AAC). Returns the film's length in seconds."""
    import av

    counts = [max(int(round(shot.seconds * FPS)), 1) for shot in shots]
    total = sum(counts)
    per_frame = RATE // FPS
    sound = np.zeros(total * per_frame, dtype=np.float32)
    cursor = 0
    for shot, count in zip(shots, counts):
        piece = shot.audio[: count * per_frame]
        sound[cursor: cursor + len(piece)] = piece
        cursor += count * per_frame

    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part.mp4")
    with av.open(str(partial), "w", options={"movflags": "+faststart"}) as container:
        video = container.add_stream("libx264", rate=FPS)
        video.width, video.height, video.pix_fmt = W, H, "yuv420p"
        video.options = {"crf": "20", "preset": "veryfast"}
        audio = container.add_stream("aac", rate=RATE)
        audio.layout = "mono"
        tag_face, caption_face = font("sans", 20), font("sans", 31)
        done = 0
        for shot, count in zip(shots, counts):
            tag = _plate(shot.tag, tag_face, DIM, (16, 9), badge=shot.number) if shot.tag else None
            starts = [c[0] for c in shot.captions]
            plates: dict[int, Image.Image] = {}
            for i in range(count):
                t = i / FPS
                frame = shot.draw(t)
                if tag:
                    frame.paste(tag, (40, 34), tag)
                k = bisect.bisect_right(starts, t) - 1
                if k >= 0 and t < shot.captions[k][1]:
                    if k not in plates:
                        plates[k] = _plate(shot.captions[k][2], caption_face, CHALK, (26, 14), width=W - 300)
                    plate = plates[k]
                    frame.paste(plate, ((W - plate.width) // 2, H - 44 - plate.height), plate)
                ImageDraw.Draw(frame).rectangle((0, H - 4, int(W * (done + 1) / total), H), fill=CITE)
                pixels = np.asarray(frame, dtype=np.uint8)
                shade = min((i + 1) / FADE, (count - i) / FADE, 1.0)
                if shade < 1:
                    pixels = (pixels * shade).astype(np.uint8)
                for packet in video.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                    container.mux(packet)
                chunk = av.AudioFrame.from_ndarray(sound[done * per_frame: (done + 1) * per_frame].reshape(1, -1), format="flt", layout="mono")
                chunk.sample_rate = RATE
                chunk.pts = done * per_frame
                for packet in audio.encode(chunk):
                    container.mux(packet)
                done += 1
                if done % 30 == 0:
                    progress(done / total)
        for stream in (video, audio):
            for packet in stream.encode(None):
                container.mux(packet)
    partial.replace(path)
    progress(1.0)
    return total / FPS
