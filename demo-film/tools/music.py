"""The film's sound bed, synthesised from oscillators and noise: no samples, no existing recording.

A slow four-chord pad (Dm9, B-flat maj9, Fmaj9, C6/9), a felt-piano voice that plays a note
or two per bar, and a few soft swells at the cuts. It is written to stay out of the way:

* wherever the real lecture is heard (the cold open, the cut in the middle, the close) the
  bed drops almost to nothing, so the lecturer's own voice is the only sound;
* under each narration line it dips by about 4 dB;
* its sections change on the film's shots, read from film/src/generated/timeline.json.

    <media-venv>/bin/python tools/music.py        ->  film/public/audio/bed.wav

The oscillator, envelope and reverb ideas follow build_music.py in this author's media kit.
"""
import json
import wave
from pathlib import Path

import numpy as np

SR = 44100
FILM = Path(__file__).resolve().parent.parent / "film"
rng = np.random.default_rng(7)

CHORDS = [
    [38, 50, 57, 65, 72, 76],   # Dm9
    [34, 46, 53, 62, 69, 72],   # Bb maj9
    [41, 48, 57, 64, 67, 72],   # F maj9
    [36, 48, 55, 64, 69, 74],   # C 6/9
]
BAR = 8.0                        # seconds per chord
MOTIF = [[(0.5, 77), (4.5, 81)], [(1.0, 74), (5.0, 77)], [(0.5, 76), (4.0, 79)], [(1.0, 74), (5.5, 81)]]


def hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def envelope(n: int, attack: float, release: float) -> np.ndarray:
    a, r = int(attack * SR), int(release * SR)
    env = np.ones(n)
    env[:a] = np.sin(np.linspace(0, np.pi / 2, a)) ** 2
    env[n - r:] = np.cos(np.linspace(0, np.pi / 2, r)) ** 2
    return env


def pad(notes: list[int], seconds: float) -> np.ndarray:
    """A soft sustained chord: each note is three slightly detuned sines with a quiet octave, left and right detuned apart."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.zeros((n, 2))
    for note in notes:
        weight = 1.0 if note < 60 else 0.7
        for channel, spread in ((0, -1), (1, 1)):
            voice = np.zeros(n)
            for cents in (-7, 0, 6):
                f = hz(note + (cents + 3 * spread) / 100)
                voice += np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28))
                voice += 0.18 * np.sin(2 * np.pi * 2 * f * t + rng.uniform(0, 6.28))
            # a slow tremor so the chord breathes
            out[:, channel] += weight * voice * (0.86 + 0.14 * np.sin(2 * np.pi * rng.uniform(0.05, 0.11) * t + rng.uniform(0, 6.28)))
    return out * envelope(n, 2.6, 3.0)[:, None] / (len(notes) * 3)


def felt(note: int, seconds: float = 4.5) -> np.ndarray:
    """A soft piano-like note: a few decaying, slightly stretched partials behind a small hammer noise."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    f = hz(note)
    y = np.zeros(n)
    for k, amp in enumerate([1.0, 0.5, 0.26, 0.12, 0.06], start=1):
        fk = f * k * (1 + 0.0004 * k * k)
        if fk < 7000:
            y += amp * np.sin(2 * np.pi * fk * t + rng.uniform(0, 6.28)) * np.exp(-t / (seconds * 0.34 / (1 + 0.4 * (k - 1))))
    hammer = rng.standard_normal(n) * np.exp(-t / 0.005) * 0.05
    y = (y * 0.5 + hammer) * envelope(n, 0.004, 0.4)
    pan = rng.uniform(0.35, 0.65)
    return np.stack([y * (1 - pan), y * pan], axis=1) * 2


def swell(seconds: float, rising: bool = True) -> np.ndarray:
    """Filtered noise that rises (into a cut) or falls (out of one)."""
    n = int(seconds * SR)
    spectrum = np.fft.rfft(rng.standard_normal(n))
    freqs = np.fft.rfftfreq(n, 1 / SR)
    spectrum *= np.exp(-((np.log2(np.maximum(freqs, 1) / 900)) ** 2) / 1.2)
    y = np.fft.irfft(spectrum, n)
    shape = np.linspace(0, 1, n) ** 2.4 if rising else np.linspace(1, 0, n) ** 2.4
    y = y / np.abs(y).max() * shape
    return np.stack([y, np.roll(y, 300)], axis=1)


def reverb(x: np.ndarray, seconds: float = 3.4) -> np.ndarray:
    n = int(seconds * SR)
    tail = rng.standard_normal((n, 2)) * np.exp(-np.arange(n) / (seconds * SR / 6))[:, None]
    tail[: int(0.02 * SR)] = 0
    size = 1 << int(np.ceil(np.log2(len(x) + n)))
    wet = np.stack([np.fft.irfft(np.fft.rfft(x[:, c], size) * np.fft.rfft(tail[:, c], size), size)[: len(x)] for c in (0, 1)], axis=1)
    return x * 0.7 + wet * (0.5 / np.abs(wet).max() * np.abs(x).max())


def add(buffer: np.ndarray, start: float, sound: np.ndarray, gain: float = 1.0) -> None:
    i = int(start * SR)
    if i >= len(buffer):
        return
    sound = sound[: len(buffer) - i]
    buffer[i : i + len(sound)] += sound * gain


def curve(total: int, points: list[tuple[float, float]]) -> np.ndarray:
    """A gain curve through (seconds, level) points, linearly interpolated then smoothed."""
    times, levels = zip(*sorted(points))
    y = np.interp(np.arange(total) / SR, times, levels)
    kernel = np.hanning(int(0.6 * SR))
    return np.convolve(y, kernel / kernel.sum(), mode="same")


def main() -> None:
    timeline = json.loads((FILM / "src/generated/timeline.json").read_text())
    seconds = timeline["seconds"]
    shot = {s["id"]: s for s in timeline["shots"]}
    total = int((seconds + 1) * SR)
    pads = np.zeros((total, 2))
    keys = np.zeros((total, 2))
    fx = np.zeros((total, 2))

    # Chords run from the freeze of the cold open to the end.
    origin = 11.3
    bar = 0
    t = origin
    while t < seconds:
        add(pads, t - 1.2, pad(CHORDS[bar % 4], BAR + 2.6))
        for beat, note in MOTIF[bar % 4]:
            add(keys, t + beat, felt(note), 0.5)
        t += BAR
        bar += 1

    # Accents: the reticle locking on, the name, the cut to the lecture and its answer, the last line.
    s3, s4, s5, s9 = shot["S3"]["start"], shot["S4"]["start"], shot["S5"]["start"], shot["S9"]["start"]
    lecture_cut = timeline["lecture"][1]
    for when, notes in ((11.6, [69]), (13.3, [74, 81]), (s3 + 0.5, [62, 74]), (s3 + 5.9, [65, 77, 84]), (lecture_cut["end"] - 0.2, [62, 69]),
                        (lecture_cut["end"] + 1.9, [77, 84]), (s9 + 1.6, [62, 74, 81]), (s9 + 8.9, [50, 65, 81])):
        for note in notes:
            add(keys, when, felt(note, 6.0), 0.75)
    for s in timeline["shots"][1:]:
        add(fx, s["start"] - 1.5, swell(1.5, rising=True), 0.05)
        add(fx, s["start"], swell(1.1, rising=False), 0.035)

    # Section levels: how present the pad and the piano are in each shot.
    level = [(0, 0.0), (10.9, 0.0), (12.2, 0.75), (shot["S2"]["start"], 0.8), (shot["S2"]["start"] + 10, 0.55), (s3, 0.85), (s4, 0.6),
             (s5, 0.72), (shot["S6"]["start"], 0.55), (shot["S7"]["start"], 0.72), (shot["S8"]["start"], 0.6), (s9, 0.7), (s9 + 7.5, 1.0),
             (seconds - 2.2, 0.9), (seconds, 0.0)]
    gain = curve(total, level)
    # Make room for the lecture and dip under narration.
    room = np.ones(total)
    for window in timeline["lecture"][1:]:
        room[int(window["start"] * SR) : int(window["end"] * SR)] = 0.1
    for cue in timeline["cues"]:
        a, b = int((cue["start"] - 0.15) * SR), int((cue["start"] + cue["seconds"] + 0.2) * SR)
        room[a:b] = np.minimum(room[a:b], 0.62)
    kernel = np.hanning(int(0.9 * SR))
    room = np.convolve(room, kernel / kernel.sum(), mode="same")

    mix = reverb(pads * 0.9 + keys * 0.55) + fx
    mix *= (gain * room)[:, None]
    mix = mix[: int(seconds * SR)]
    mix *= 0.30 / np.abs(mix).max()          # the bed peaks well below the voice (which peaks at 0.7)
    out = FILM / "public/audio/bed.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype("<i2").tobytes())
    rms = float(np.sqrt((mix ** 2).mean()))
    print(f"{out}: {seconds:.1f} s, {bar} bars, peak {np.abs(mix).max():.2f}, rms {rms:.3f}")


if __name__ == "__main__":
    main()
