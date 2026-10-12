"""Narration for the film: every line of film/src/script.json -> film/public/voice/<id>.wav.

Voice: Kokoro-82M (hexgrad/kokoro, Apache-2.0) through the `nw_media.speak` helper of this
author's media kit. Lines are cached by text, voice and rate, so editing one line re-voices
only that line. Durations are written to film/src/generated/voice.json for the timeline.

    <media-venv>/bin/python tools/voice.py
"""
import hashlib
import json
import os
import sys
from pathlib import Path

# `nw_media` is the author's small media kit: a wrapper around Kokoro-82M with a per-line cache.
# Point PRAMANA_MEDIA_KIT at the folder that holds it; any text-to-speech that writes the same
# wav files and voice.json would serve.
KIT = Path(os.environ["PRAMANA_MEDIA_KIT"])
sys.path.insert(0, str(KIT))
import nw_media as M  # noqa: E402

FILM = Path(__file__).resolve().parent.parent / "film"


def main() -> None:
    script = json.loads((FILM / "src/script.json").read_text())
    voice, rate = script["voice"], script["rate"]
    cache = FILM.parent / "tools/voice-cache"
    out = FILM / "public/voice"
    cache.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    durations = {}
    for line_id, line in script["lines"].items():
        spoken = line["say"] if isinstance(line, dict) and line.get("say") else (line["text"] if isinstance(line, dict) else line)
        key = hashlib.sha1(f"{spoken}|{voice}|{rate}".encode()).hexdigest()[:12]
        wav = cache / f"{key}.wav"
        samples = M.speak(spoken, wav, voice, rate)          # cached on disk; returns the line with silence trimmed
        M.write_wav(out / f"{line_id}.wav", samples)
        durations[line_id] = round(len(samples) / M.SR, 3)
        print(f"{line_id}  {durations[line_id]:5.2f} s  {spoken}")
    (FILM / "src/generated").mkdir(parents=True, exist_ok=True)
    (FILM / "src/generated/voice.json").write_text(json.dumps(durations, indent=1))
    print(f"{len(durations)} lines, {sum(durations.values()):.1f} s of speech")


if __name__ == "__main__":
    main()
