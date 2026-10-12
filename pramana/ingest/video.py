"""Lecture videos -> timestamped units from two channels: what is said and what is on the board.

* Speech: faster-whisper with word timestamps, grouped into ~40 s passages that start and
  end on sentence boundaries. A citation seeks the player to the passage's first word.
* Board: one frame taken at the end of each passage (when the board is fullest), read by the
  vision model into LaTeX equations and a description of the drawing.

Transcripts are cached per file hash in `data/asr_cache/`, so re-ingesting (or replaying on
another machine) does not need to run speech recognition again.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from ..config import settings
from . import vision
from .common import file_digest

TARGET_SECONDS = 40.0
MAX_SECONDS = 60.0


def transcribe(path: Path) -> list[dict]:
    """Word-level transcript: [{"w": " word", "s": start, "e": end}, ...]."""
    cache = settings.data_dir / "asr_cache" / f"{file_digest(path)}.json"
    if cache.exists():
        return json.loads(cache.read_text())["words"]
    from faster_whisper import WhisperModel

    model = _whisper()
    segments, _ = model.transcribe(
        str(path), language="en", beam_size=5, temperature=0.0, vad_filter=True, word_timestamps=True
    )
    words = [
        {"w": word.word, "s": round(word.start, 2), "e": round(word.end, 2)}
        for segment in segments
        for word in (segment.words or [])
    ]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"file": path.name, "model": settings.whisper_model, "words": words}))
    return words


_model = None


def _whisper():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(settings.whisper_model, device="cpu", compute_type="int8")
    return _model


def passages(words: list[dict]) -> list[dict]:
    """Group words into passages of about TARGET_SECONDS that break at sentence ends."""
    out: list[dict] = []
    current: list[dict] = []
    for index, word in enumerate(words):
        current.append(word)
        duration = word["e"] - current[0]["s"]
        sentence_end = word["w"].rstrip().endswith((".", "?", "!"))
        last = index == len(words) - 1
        if last or (sentence_end and duration >= TARGET_SECONDS) or duration >= MAX_SECONDS:
            text = "".join(w["w"] for w in current).strip()
            if text:
                out.append({"t_start": current[0]["s"], "t_end": current[-1]["e"], "text": text})
            current = []
    # A trailing fragment of a few words reads better attached to the passage before it.
    if len(out) >= 2 and len(out[-1]["text"].split()) < 12:
        tail = out.pop()
        out[-1]["text"] += " " + tail["text"]
        out[-1]["t_end"] = tail["t_end"]
    return out


def grab_frames(path: Path, times: list[float], targets: list[Path]) -> None:
    """Save the frame nearest each timestamp as a JPEG."""
    import av

    todo = [(t, target) for t, target in zip(times, targets) if not target.exists()]
    if not todo:
        return
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        for time, target in todo:
            container.seek(int(max(time - 1.0, 0) / stream.time_base), stream=stream, backward=True)
            chosen = None
            for frame in container.decode(stream):
                chosen = frame
                if frame.time is not None and frame.time >= time:
                    break
            if chosen is not None:
                chosen.to_image().convert("RGB").save(target, quality=85)


def clock(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def ingest_video(
    source: dict,
    path: Path,
    asset_dir: Path,
    progress: Callable[[str], None] = print,
    use_vision: bool = True,
    workers: int = 4,
) -> list[dict]:
    digest = file_digest(path)
    asset_dir.mkdir(parents=True, exist_ok=True)
    spoken = passages(transcribe(path))
    frame_times = [max(p["t_end"] - 0.5, 0.0) for p in spoken]
    frame_paths = [asset_dir / f"f{int(p['t_start']):05d}.jpg" for p in spoken]
    grab_frames(path, frame_times, frame_paths)

    boards: dict[int, dict] = {}
    if use_vision:
        def read(index: int) -> tuple[int, dict]:
            return index, vision.read_frame(
                frame_paths[index],
                spoken[index]["text"],
                cache_key=["frame", vision.FRAME_PROMPT_VERSION, digest, int(spoken[index]["t_start"])],
            )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            boards = dict(pool.map(read, [i for i, f in enumerate(frame_paths) if f.exists()]))

    units = []
    for index, passage in enumerate(spoken):
        second = int(passage["t_start"])
        locator = {"t_start": passage["t_start"], "t_end": passage["t_end"]}
        frame_asset = f"{source['id']}/{frame_paths[index].name}" if frame_paths[index].exists() else None
        transcript_id = f"{source['id']}:t{second}"
        frame_id = f"{source['id']}:f{second}"
        board = boards.get(index)
        has_board = bool(board and board.get("has_content") and (board.get("board") or board.get("equations")))
        units.append({
            "id": transcript_id,
            "source_id": source["id"],
            "kind": "transcript",
            "modality": "speech",
            "locator": {**locator, **({"sibling": frame_id} if has_board else {})},
            "section": source["title"],
            "text": passage["text"],
            "asset": frame_asset,
        })
        if has_board:
            parts = [f"On the board at {clock(frame_times[index])}: {board['board'].strip()}"]
            if board.get("equations"):
                parts.append("Written on the board: " + "; ".join(f"${e}$" for e in board["equations"]))
            units.append({
                "id": frame_id,
                "source_id": source["id"],
                "kind": "frame",
                "modality": "vision",
                "locator": {**locator, "t_frame": round(frame_times[index], 2), "sibling": transcript_id},
                "section": source["title"],
                "text": "\n\n".join(parts),
                "asset": frame_asset,
            })
    for order, unit in enumerate(units):
        unit["ord"] = order
    progress(f"{source['id']}: {len(spoken)} passages, {sum(1 for u in units if u['kind'] == 'frame')} board readings")
    return units
