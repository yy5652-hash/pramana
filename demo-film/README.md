# The Pramana film

The demo film for [Pramana](../README.md), about four minutes, 1920×1080 at 30 fps. It is built from
code, so every picture and every number in it can be traced and rebuilt.

## What is real in it

| What you see | Where it comes from |
|---|---|
| The lecturer at the glass board | MIT OpenCourseWare 8.01SC lecture videos, the same files the product ingests. Not re-enacted, not generated. |
| The product on screen | Screen recordings of the running app, driven by real mouse and keyboard events in headless Chrome (`takes/record.mjs`, `takes/scenes.mjs`). The answers, citations, quiz feedback and study plan are what the app returned during the take. |
| Textbook pages and slides | Renders of the course files the product ingests. |
| Every number and chart | `film/public/data/film.json`, written by `tools/export_data.py` from the knowledge base and from `evaluation/results/*.json` in the product repository. Nothing is typed into a shot by hand. |
| The narration | Synthesised (Kokoro-82M, voice `af_heart`) from `film/src/script.json`. |
| The music | Synthesised by `tools/music.py` (numpy). No samples, no third-party recording. |

The cuts follow the takes, not the other way round: `film/src/timing.ts` derives every
duration and narration cue from the marks a take recorded, so re-recording a take re-times
the film.

## Rebuild

The product must be built and running first (see the main README), because the takes record
it. From this folder:

```bash
cd film && npm install && cd ..                                          # Remotion and KaTeX
node takes/record.mjs ask refuse hinglish practice lessons progress map library   # screen takes of the running app
../.venv/bin/python tools/export_data.py                                 # footage, pages and numbers
python tools/voice.py                                                    # narration from film/src/script.json
sh tools/render.sh                                                       # timeline, music, render, loudness
```

`tools/render.sh` writes `film/out/pramana-film.mp4` and `film/out/pramana-film.srt`
(English subtitles, timed from the narration). Sound is mastered to −16 LUFS.

Three things are read from the environment because they differ per machine: `FFMPEG` (an
ffmpeg binary; default `ffmpeg` on the path), `CHROME` (the browser the takes are recorded
in; default Google Chrome under `~/Applications`), and `PRAMANA_MEDIA_KIT`, the folder of the
small text-to-speech wrapper `tools/voice.py` imports. That wrapper is not in this
repository; it does nothing but call Kokoro-82M and cache each line, and any text-to-speech
that writes `film/public/voice/<line>.wav` and `film/src/generated/voice.json` will serve.
The footage, page renders and take recordings are not in the repository either (they are
large, and the footage is under its own licence): `export_data.py` and `record.mjs` recreate
them from the course files and the running app.

## What was reused

* **[Remotion](https://www.remotion.dev)** 4.0 renders the film. Remotion has its own
  licence: free for individuals and small teams, paid for larger companies.
* **[Vincentwei1021/video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft)**
  (Apache-2.0), commit `e1d15d9`: the Remotion project scaffold, and its rule sheets for
  rhythm, type and camera were read as a reference. The shots and components in
  `film/src` were written for this film. A copy is kept in `vendor/` for reference and is
  not part of the build.
* **[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)** (Apache-2.0) for the voice.
* **KaTeX** (MIT) typesets the formulas.

## Licences of the material shown

* Lecture footage: MIT OpenCourseWare, *8.01SC Classical Mechanics* (Fall 2016), CC BY-NC-SA 4.0.
* Textbook pages: OpenStax, *University Physics Volume 1*, CC BY-NC-SA 4.0 (as stated in the PDF used).
* Slides: Collin College PHYS 2425 lecture slides, CC BY 4.0.

Because it contains the MIT footage and the textbook pages, the finished film is released under
**CC BY-NC-SA 4.0**. The source code in this directory is MIT-licensed like the product.

## AI assistance

The film was written, cut and rendered by Claude Code (Anthropic) under my direction: I
asked for a film that works as a piece of art, uses real footage, and shows real evidence.
The narration voice is a text-to-speech model. No image or video generation model was used;
every frame is footage, a recording of the app, or typography and charts drawn by code.
