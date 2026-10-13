# Pramana

**A study companion that can only say what your course says, and shows you exactly where.**

*Pramāṇa* (प्रमाण) is Sanskrit for proof: the means by which something is known. Pramana
reads a course's textbook, slide decks and lecture videos, and then tutors and tests a
student from that material alone. Every sentence of an answer carries a number; the number
opens the textbook page with the passage outlined, the slide, or the lecture video at the
second it was said. When the material does not cover a question, the tutor says so. And when
a student needs a concept taught, it cuts them a short narrated film of it from those same
pages, slides and lectures.

Built for Track D (Personalized Tutoring & Adaptive Learning) of the Multimodal AI
Hackathon 2026.

- **Demo film (4:21):** https://youtu.be/63be_42pV3k
- **Devpost:** https://devpost.com/software/pramana-v7si9t
- **Docs:** [architecture](docs/architecture.md) · [grounding](docs/grounding.md) · [learner model](docs/learner-model.md) · [lessons](docs/lessons.md) · [evaluation method](docs/evaluation.md) · [results](docs/results.md)

## Results at a glance

Sample course: introductory mechanics from one textbook (OpenStax *University Physics*,
4 chapters), 4 slide decks and 16 MIT lecture videos. Every figure below is generated from
`evaluation/results/*.json` by `python -m evaluation.report`.

<!-- results:start -->
| Measured | Result |
|---|---|
| Citable units from 21 sources | 961 (64% needed vision to read) |
| Questions verified / rejected before use | 207 / 21 |
| Retrieval hits the exact page, slide or passage (n = 39) | hit@1 0.64, hit@3 0.87, MRR 0.76 |
| Context recall with vision / without (n = 39) | 1.00 / 0.77 |
| RAGAS (n = 39) | faithfulness 0.96, answer relevancy 0.91, context precision 0.92, context recall 1.00 |
| Off-material questions declined | 14 of 14 |
| In-material questions answered | 39 of 39 |
| Answer segments fully supported by their own citations | 98% of 58 |
| Lesson films: narration lines supported by the source on screen | 99% of 77 (19 lessons; 0 scenes dropped by code) |
| Simulated students: gain in true proficiency (720 runs) | adaptive +0.098, syllabus order +0.110, random +0.061 |
| Repeated questions served by the selector | 0.0% |
<!-- results:end -->

Where the product loses is in the same report: against a plain syllabus-order baseline the
adaptive policy is slightly behind overall: ahead for novices, worse for fast learners. See
[evaluation.md](docs/evaluation.md#what-the-simulation-shows-now-including-where-the-product-loses).

## What it does

| Requirement of the brief | How Pramana meets it | Where |
|---|---|---|
| Ingest lecture videos, textbooks and slide decks without manual preprocessing | Drop in a PDF, PPTX or video. Pages are rendered and read by a vision model; decks are parsed (including Office Math that ordinary extractors skip) and rendered; video is transcribed and one frame per passage of the board is read | `pramana/ingest/` |
| Every unit linked to its origin | 961 units, each with a page and rectangle, a slide number, or a start and end time | `units.locator`, `pramana/cite.py` |
| Topics, concepts, prerequisites; every unit tagged | 4 topics, 19 concepts, 22 prerequisite edges forced into a DAG; 951 of 961 units tagged | `pramana/ingest/concepts.py` |
| Use information from figures and diagrams | 119 figures described with bounding boxes; 83 board readings; equations restored as LaTeX | `pramana/ingest/vision.py` |
| Cited answers that open the exact page, slide or timestamp | Answers are returned as segments that each name their sources; the viewer opens the page image with the passage outlined, the slide, or the video seeked to the second | `pramana/tutor.py`, `web/js/viewer.js` |
| Decline or flag what the material does not cover; keep outside knowledge separate | Two refusal gates; outside knowledge only on request and only in a separately labelled block | `pramana/tutor.py`, [grounding.md](docs/grounding.md) |
| Quizzes and mock exams: MCQ, short answer, numerical; tagged to topic, source and difficulty | 207 verified questions, each tied to a concept, source units and a difficulty from 1 to 5 | `pramana/assess/` |
| Verify question correctness; avoid repeats | Structure check, arithmetic recomputation of numerical keys, blind solve by a different model, near-duplicate filter; an attempted question is never served again | `pramana/assess/generate.py`, `select.py` |
| Cited feedback; report with weak topics and likely misconceptions | Every MCQ distractor is written with the misconception it catches; wrong numbers are matched against slip signatures; the report traces weak topics to their weakest prerequisite | `pramana/assess/grade.py`, `session.py` |
| Per-topic mastery that updates after every quiz and conversation | Bayesian knowledge tracing with item-aware guess and slip, forgetting, and evidence that flows along the prerequisite map; chat messages are read as evidence too | `pramana/learner.py`, [learner-model.md](docs/learner-model.md) |
| New students | A 10-question diagnostic that picks the most informative item each time, or an intake conversation | `Selector.diagnostic_question` |
| Evaluate with a standard framework; simulated students | RAGAS on a 53-question test set with known source locations; 720 simulated students across 6 profiles and 3 policies | `evaluation/` |
| A lesson, not only an answer | For the concept the learner model recommends (or one the student picks), a narrated film of about two minutes cut from the course itself: the page with the passage outlined and the quoted words lit, the slide, the lecture in the lecturer's own voice, the textbook's own worked example one step at a time, the student's own wrong answer from practice with the slip named, what to keep, and one checked question they have not met. Scenes that cannot be tied to a source are dropped by code; every scene is clickable to its source | `pramana/lesson/`, [lessons.md](docs/lessons.md) |
| Optional: course map, revision material, schedule, Indian-language interaction, audio | Interactive prerequisite map coloured by mastery; cited flashcards with an audio brief; a study plan from weak topics and forgetting curves; answers in Hindi or Hinglish; voice input and read-aloud | `web/`, `pramana/schedule.py`, `pramana/revision.py` |

## Quick start

Requirements: Python 3.11 or newer and [uv](https://docs.astral.sh/uv/). No Node, no
Docker, no office suite, no system ffmpeg. About 2 GB of disk for the course files, models
and rendered pages. The first lesson film also downloads the narrator's voice (120 MB).

```bash
git clone https://github.com/yy5652-hash/pramana && cd pramana
make setup                      # virtual environment and dependencies
cp .env.example .env            # then put an API key in LLM_API_KEY (see below)
make fetch                      # downloads the open course files, about 470 MB
make ingest                     # builds the knowledge base and the concept map
make bank                       # generates and verifies the question bank
make serve                      # http://127.0.0.1:8000
```

**Without an API key.** The repository includes the cached replies of every model call
used to build the sample course and to run the evaluation, plus the speech transcripts.
`make replay` rebuilds the knowledge base, the question bank and every evaluation result
from those caches without touching the network (after `make fetch`). The live tutor needs a
key, because a new question is a new request.

**Any OpenAI-compatible endpoint works.** Set `LLM_BASE_URL` and `LLM_API_KEY` in `.env`.
The default is Google's Gemini endpoint, whose free tier is enough to build and run the
sample course. For a local model: `LLM_BASE_URL=http://localhost:11434/v1` (Ollama) and set
the `PRAMANA_*_MODELS` variables to a model that accepts images.

**Your own course.** Open the app, go to Library, and drop in a PDF, a PPTX or a lecture
video. Or write a manifest like `course/mechanics/course.yaml` and run the same three
commands with your course id.

## Using it

- **Tutor.** Ask a question. Click a number to open its source. Switch the answer language
  to Hindi or Hinglish. Tick *Allow outside knowledge* to also get a labelled answer for
  things the course does not cover. Answer the check question and watch your mastery move.
- **Lessons.** *Cut this lesson* makes a film of about two minutes on the concept you most
  need, from your own course, in under a minute: the idea, the rule, a worked example from the
  textbook, a mistake (your own, once you have answered something wrongly in Practice), what
  to keep, and one question. Beside the player, every scene lists the source it shows.
- **Practice.** Start with the diagnostic if you are new. Quizzes pick each next question
  from your weakest ready concept; mock exams cover a scope evenly.
- **Progress.** Mastery per concept, every update that produced it, a study plan and
  flashcards for your weakest topics.
- **Course map.** The prerequisite graph, coloured by your mastery.
- **Library.** What is in the knowledge base and how each piece was read. Upload here.
- **Evidence.** The evaluation results, drawn from the result files.

## How it works, briefly

```
PDF ─► render page ─┐
PPTX ─► parse + draw ├─► vision model ─► units with locators ─► embeddings ─► hybrid retrieval ─► tutor
video ─► ASR, frames ┘                         │                                   (cited segments, or decline)
                                               └─► concept map ─► verified question bank ─► adaptive assessment
                                                        └──────────► learner model ◄──── answers, conversations
```

Three decisions shape the system:

1. **Vision is in the main path, because the text is not enough.** This textbook's PDF has
   no equations in its text layer: they are vector drawings. The slide decks hide theirs in
   Office Math blocks that python-pptx skips. 64 % of the knowledge base could not have
   been read without a vision model.
2. **Grounding is enforced by code.** The model must answer in segments that name their
   sources. A segment without a valid source is deleted before display, and an answer with
   no surviving segment becomes a refusal.
3. **Nothing reaches a student unchecked.** A question enters the bank only if arithmetic
   reproduces its key (for numerical items) and a different model, solving it blind, agrees.
   11 % of drafts were rejected.

More in [architecture.md](docs/architecture.md).

## Evaluation

```bash
make eval      # retrieval, vision ablation, grounding, RAGAS, simulated students, report
make test      # 55 unit tests: learner model, selection, grading, scheduling, parsing helpers, lessons
```

Method, limits and the failed first attempt at the adaptive policy are written up in
[evaluation.md](docs/evaluation.md). Results are in [results.md](docs/results.md).

## Repository layout

```
pramana/            the package
  ingest/           pdf.py, slides.py, video.py, vision.py, concepts.py
  assess/           generate.py (generation + verification), select.py, grade.py, session.py, numeric.py
  tutor.py          the grounded tutor
  lesson/           script.py (storyboard, grounded by code), build.py, render.py (the film), typeset.py (formulas on cards), voice.py
  learner.py        the learner model
  retrieve.py       BM25 + dense + re-ranking
  llm.py            one client for any OpenAI-compatible endpoint: cache, replay, fallback chains
  api.py            FastAPI routes; serves web/
web/                the browser app (plain ES modules, no build step; KaTeX vendored)
evaluation/         test set, retrieval, grounding, RAGAS, ablation, simulated students, report
course/mechanics/   the sample course manifest (what to download, and its licences)
data/llm_cache/     cached model replies (committed; this is what replay reads)
data/asr_cache/     cached speech transcripts (committed)
docs/               architecture, grounding, learner model, lessons, evaluation method, results
tests/              unit tests
demo-film/          the demo film's source: Remotion shots, the scripts that record the app, and its tools
```

## Limits

- One course, in English, in one subject. Nothing here has been tried on a humanities
  course or on scanned handwriting.
- Evaluated on 53 questions and on simulated students. No real student has used it.
- Lecture videos need a visible board or slides; a talking head adds only its transcript.
- Slide previews are redrawn from the deck's shapes, so themes and animations are lost.
- Lesson films are cut, not generated: a concept the course says little about gets no
  lesson, the worked example is the textbook's own and not a new one, and the narrator
  speaks English only.
- The learner model's parameters were chosen by reasoning and simulation, not fitted to
  student data.
- More in [evaluation.md](docs/evaluation.md#7-limits-of-the-whole-evaluation).

## Licences and attribution

Code: MIT ([LICENSE](LICENSE)). The sample course is built from openly licensed material
that this repository does not redistribute; `make fetch` downloads it from its publishers.
Sources, licences and third-party software are listed in [NOTICE.md](NOTICE.md). Because the
textbook and the lecture videos are CC BY-NC-SA, the sample course is for non-commercial
use.

- Textbook: Ling, Sanny, Moebs et al., *University Physics Volume 1*, OpenStax. Access for free at <https://openstax.org/details/books/university-physics-volume-1>
- Slides: Collin College Physics Department, PHYS 2425 Lecture Slides, CC BY 4.0
- Lectures: MIT OpenCourseWare, 8.01SC Classical Mechanics, Fall 2016, CC BY-NC-SA 4.0

## AI assistance

The hackathon rules ask for this to be stated plainly.

- **Claude Code (Anthropic)** wrote the code, the tests, the documentation and the demo
  film's pipeline. That is every file in this repository. It also proposed the
  architecture and picked the sample course. I chose the track, set the direction
  (including the film's) and decided what was submitted.
- **Gemini models** (Google) run inside the product: `gemini-3.5-flash-lite` for vision
  reading, tagging, tutoring and judging; `gemini-3.8-flash` and `gemini-3.6-flash` for the
  concept map and for writing questions when their free quota allowed. They also drafted
  35 of the 53 test questions; Claude Code checked each draft against its source, dropped
  two and wrote the rest. No human expert reviewed the test set.
- **Local models:** Whisper `small.en` (speech), `bge-small-en-v1.5` (embeddings),
  `ms-marco-MiniLM-L-6-v2` (re-ranking), Kokoro-82M (the narrator of the lesson films).
- **Film:** narration by Kokoro-82M; composition in Remotion, starting from the
  video-shotcraft template (Apache-2.0). Its source is in [demo-film/](demo-film/README.md).

Author: Yi Yu.
