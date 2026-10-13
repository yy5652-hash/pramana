"""The narrator's voice: Kokoro-82M through onnxruntime, entirely on this machine.

The model (about 120 MB with its voices) is downloaded once, on first use, into
`data/models/kokoro/`. Every spoken line is cached by its text, so making the same lesson
twice costs no synthesis.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
import threading
import wave
from pathlib import Path
from typing import Callable

import numpy as np

from ..config import settings

SR = 24000                      # Kokoro's sample rate
RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin")
VOICES = {"en": ("af_heart", "en-us")}
ESPEAK_PATH = 140               # espeak-ng keeps the path of its data in a buffer of 160 characters

_engine = None
_lock = threading.Lock()


def model_dir() -> Path:
    return settings.data_dir / "models" / "kokoro"


def available() -> bool:
    """True when a voice can be produced (the package is installed)."""
    try:
        import kokoro_onnx  # noqa: F401
    except ImportError:
        return False
    return True


def _espeak():
    """Where the phonemiser finds its data, when the usual place will not do.

    espeak-ng holds that path in a fixed buffer and, given a longer one, looks instead where it
    was built, on someone else's machine. So for an install deep in the file system the data
    is copied once to a short path in the temporary directory. A link would not do: the
    phonemiser resolves it back to the long path."""
    import espeakng_loader
    from kokoro_onnx import EspeakConfig

    data = espeakng_loader.get_data_path()
    if len(data) < ESPEAK_PATH:
        return None
    name = "pramana-espeak-" + hashlib.sha1(data.encode()).hexdigest()[:10]
    for place in (Path(tempfile.gettempdir()), Path("/tmp"), Path.home()):
        if not place.is_dir():
            continue
        copy = place.resolve() / name
        if len(str(copy)) >= ESPEAK_PATH:
            continue
        try:
            if not (copy / "phontab").exists():
                shutil.copytree(data, copy, dirs_exist_ok=True)
        except OSError:
            continue
        return EspeakConfig(data_path=str(copy))
    return None


def _load(progress: Callable[[str], None]):
    global _engine
    with _lock:
        if _engine is None:
            import httpx
            from kokoro_onnx import Kokoro

            target = model_dir()
            target.mkdir(parents=True, exist_ok=True)
            for name in FILES:
                path = target / name
                if not path.exists():
                    progress(f"downloading the narrator's voice ({name}), once")
                    partial = path.with_suffix(path.suffix + ".part")
                    with httpx.stream("GET", RELEASE + name, follow_redirects=True, timeout=120) as response:
                        response.raise_for_status()
                        with partial.open("wb") as handle:
                            for block in response.iter_bytes(1 << 20):
                                handle.write(block)
                    partial.rename(path)
            _engine = Kokoro(str(target / FILES[0]), str(target / FILES[1]), espeak_config=_espeak())
        return _engine


def spoken(text: str) -> str:
    """What the narrator should actually say: no markup, no stray symbols."""
    text = re.sub(r"\$+", "", text)
    text = re.sub(r"[*_#`]+", "", text)
    text = text.replace("&", " and ").replace("≈", " approximately ").replace("=", " equals ").replace("≥", " at least ").replace("≤", " at most ")
    return " ".join(text.split())


def speak(text: str, language: str = "en", speed: float = 1.0, progress: Callable[[str], None] = lambda _: None) -> np.ndarray:
    """One line of narration as mono float32 samples at `SR`, with the silence at both ends trimmed."""
    say = spoken(text)
    voice, lang = VOICES.get(language, VOICES["en"])
    cache = settings.data_dir / "tts_cache"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / (hashlib.sha1(f"{voice}|{speed}|{say}".encode()).hexdigest()[:16] + ".wav")
    if path.exists():
        with wave.open(str(path), "rb") as handle:
            return np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16).astype(np.float32) / 32767.0
    samples, _ = _load(progress).create(say, voice=voice, speed=speed, lang=lang)
    samples = np.asarray(samples, dtype=np.float32)
    loud = np.flatnonzero(np.abs(samples) > 0.01)
    if len(loud):
        samples = samples[max(loud[0] - SR // 20, 0): loud[-1] + SR // 10]
    peak = float(np.abs(samples).max()) if len(samples) else 0.0
    if peak > 0:
        samples = samples * (0.85 / peak)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())
    return samples
