# Notices

The MIT licence in `LICENSE` covers the code in this repository. It does not cover the
course material the sample course is built from, or the third-party software below.

## Course material (not redistributed here)

`pramana fetch mechanics` downloads these files from their publishers. The repository
contains none of them. It does contain text derived from them (cached model transcriptions
in `data/llm_cache/`, speech transcripts in `data/asr_cache/`, and the excerpts quoted in
`evaluation/`); that derived text stays under the licence of its source.

| Source | Licence | Attribution |
|---|---|---|
| *University Physics Volume 1*, OpenStax | CC BY-NC-SA 4.0 | Ling, Sanny, Moebs et al., OpenStax, Rice University. Access for free at https://openstax.org/details/books/university-physics-volume-1 |
| PHYS 2425 Lecture Slides, chapters 3, 5, 6, 7 | CC BY 4.0 | Collin College Physics Department, https://digitalcommons.collin.edu/physics/ (adapted from OpenStax *University Physics*) |
| 8.01SC Classical Mechanics, Fall 2016 (16 lecture videos) | CC BY-NC-SA 4.0 | Chakrabarty, Dourmashkin, Tomasik, Frebel, Vuletic. MIT OpenCourseWare, https://ocw.mit.edu/courses/8-01sc-classical-mechanics-fall-2016/ |

Because two of the three sources are non-commercial share-alike, the sample course and
anything built from it may be used for non-commercial purposes only.

## Third-party software

| Component | Use | Licence |
|---|---|---|
| KaTeX 0.16.11 (vendored in `web/vendor/katex`) | maths rendering in the browser | MIT |
| pypdfium2 / PDFium | PDF rendering and text layer | Apache-2.0 / BSD-3-Clause |
| python-pptx | slide parsing | MIT |
| faster-whisper, CTranslate2, Whisper `small.en` weights | speech recognition | MIT |
| PyAV / FFmpeg libraries | video decoding; encoding of the lesson films (H.264 through the x264 build inside PyAV's wheels, which this repository does not redistribute) | BSD-3-Clause / LGPL, x264 GPL-2.0 |
| kokoro-onnx, Kokoro-82M weights | the narrator's voice in lesson films, run locally | MIT / Apache-2.0 |
| fastembed, ONNX Runtime | local embeddings and re-ranking | Apache-2.0 / MIT |
| `BAAI/bge-small-en-v1.5` | embedding model | MIT |
| `Xenova/ms-marco-MiniLM-L-6-v2` | cross-encoder re-ranker | Apache-2.0 |
| FastAPI, Uvicorn, httpx, NumPy, Pillow, PyYAML | web server and utilities | MIT / BSD / HPND |
| RAGAS (evaluation only) | answer-quality metrics | Apache-2.0 |
