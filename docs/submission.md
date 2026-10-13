# Devpost submission text

Copy for the project page. Every number is from `docs/results.md`.

**Name:** Pramana

**Tagline:** A study companion that can only say what your course says, shows exactly where, and turns any concept into a narrated teaching video cut from your own textbook, slides and lectures.

**Track:** D: Personalized Tutoring & Adaptive Learning

**Links:** repository `https://github.com/yy5652-hash/pramana` · video https://youtu.be/63be_42pV3k · project page https://devpost.com/software/pramana-v7si9t

**Built with:** Python, FastAPI, SQLite, NumPy, pypdfium2, python-pptx, faster-whisper,
fastembed (bge-small-en-v1.5, ms-marco-MiniLM), PyAV, Pillow, Gemini API (gemini-3.5-flash-lite,
gemini-3.1-flash-lite, gemini-3.8-flash, gemini-3.6-flash), Kokoro-82M (kokoro-onnx), RAGAS, KaTeX,
vanilla JavaScript, Remotion, Claude Code

---

**Give it a concept and it makes the teaching video.** For any concept of the course, the
one the learner model says you most need or one you pick, Pramana writes, voices and cuts a
narrated lesson film on your own laptop in under a minute. The film is built only from your
course: the textbook page with the passage outlined and the quoted words lit, the slide, the
lecture in your lecturer's own voice. No generated imagery, no stock footage, and every
scene opens its source. It made one for each of the 19 concepts of the sample course; the
demo video shows one being made at 2:59.

## Inspiration

A course says everything three times: on the board, in the textbook, on a slide. A student
revising at midnight remembers that it was explained somewhere and cannot find where. A
general chatbot will answer the question fluently, from somewhere else entirely, in a
notation the course never used, and with no way to check it.

*Pramāṇa* is Sanskrit for proof: the means by which something is known. We wanted a tutor
that is not allowed to say anything it cannot point to.

## What it does

Pramana reads a course's textbook, slide decks and lecture videos with no preparation, and
then tutors and tests a student from that material alone.

- **Every answer shows its proof.** Each sentence of an answer carries a number. Clicking it
  opens the textbook page with the passage outlined, the slide, or the lecture video at the
  second it was said.
- **It generates a teaching video for any concept.** Choose a concept, or let the learner
  model choose the one you are weakest on and ready for, and it produces a short narrated
  film that teaches it: an MP4 you can play in the app or download. One model call writes
  the storyboard; code keeps only the scenes it can tie to a source; the narration is voiced
  locally; the film is drawn and encoded on your machine. It opens with the prerequisite if
  yours is shaky, follows your level on the concept, and ends by sending you to checked
  questions on it.
- **It declines.** If the material does not cover a question, it says so and points to the
  nearest thing the course does cover. Outside knowledge appears only if the student asks
  for it, in a separate labelled block.
- **It tests with checked questions.** MCQ, short-answer and numerical questions are
  generated from the course and enter the bank only after arithmetic recomputes the key and
  a second model, solving blind, agrees. 228 were drafted; 21 were rejected.
- **It reads a wrong answer.** Each distractor is written with the misconception it
  catches; wrong numbers are matched against slip signatures such as a reversed sign or a
  km/h–m/s mix-up. The report traces a weak topic to the prerequisite underneath it.
- **It models the learner.** Bayesian knowledge tracing with item-aware guess and slip,
  forgetting, and evidence that flows along a prerequisite map. It updates after every
  quiz answer and every conversation, and every update is shown with its reason.
- **And the rest:** a course map coloured by mastery, cited flashcards with an audio brief,
  a study plan built from weak topics and forgetting curves, answers in Hindi or Hinglish,
  voice input.

## How we built it

**Ingestion.** The textbook's PDF has no equations in its text layer; they are vector
drawings. The slide decks keep theirs in Office Math blocks that standard extractors skip.
So every page, every slide with a picture or an equation, and one frame per spoken passage
of each lecture is read by a vision-language model, which restores the maths as LaTeX and
describes each figure. Speech is transcribed locally with word timestamps. The result is
961 citable units, each remembering its page and rectangle, its slide, or its second.
64 % of them could not have been read without vision.

**Grounding by construction.** The tutor model must answer in segments that each name their
sources. Code deletes any segment without a valid source, and an answer with no surviving
segment becomes a refusal. Retrieval is BM25 plus dense vectors, fused and re-ranked, all
local.

**Assessment and the learner model.** A concept map (19 concepts, 22 prerequisite links) is
extracted from the course outline and forced into a DAG. Questions are generated per
concept from that concept's own passages. The selector picks the next question from the
learner model: the weakest concept the student is ready for, at a difficulty they should
get right about 85 % of the time.

**Lessons as film.** One model call writes a storyboard: which sources to show, what the
narrator says over each, the steps of the textbook's worked example, a few sentences on the
student's mistake, and what to keep. Code then keeps only what it can tie to a source: the
words to be lit on a page must be in that passage word for word, the stretch of lecture to
be heard must be found in the word-level transcript, the example's steps must follow the
textbook's order, and a point of the recap is written on the scene whose source states it. The mistake
and the closing question come from the question bank and the student's own attempts, not
from the model. The page is re-rendered from the PDF for a sharp close-up, the quoted words
are located by the PDF's own character positions, formulas on the cards are set with the
KaTeX fonts by a small typesetter of our own, the narration is voiced locally (Kokoro), and
the film is drawn with Pillow and encoded with PyAV. No Manim, no TeX, no stock footage.

**One model client.** Any OpenAI-compatible endpoint works. Every reply is cached, and in
replay mode the knowledge base, the question bank and the whole evaluation rebuild from the
committed cache without an API key.

## Challenges we ran into

- **The equations were not there.** The first text-only ingestion produced a physics course
  with no formulas in it. That finding reorganised the whole pipeline around vision.
- **A free-tier model budget.** The larger models allowed about twenty requests a day. The
  system had to be built so that a small fast model does the volume and every call is
  cached, rate-limited and able to fall back.
- **Our adaptive policy lost.** In the first simulation it was beaten by simply following
  the syllabus. Tracing simulated students showed why (one easy correct answer was read as
  mastery; one wrong answer collapsed belief), and fixing those brought it close to the
  syllabus baseline overall and ahead of it for novices. It still loses for fast learners,
  and the report says so.
- **LaTeX inside JSON.** Models double-escape backslashes or drop them (`\frac` arrives as
  a form feed followed by "rac"). A repair step now runs on every parsed reply.

## Accomplishments that we're proud of

- A citation that opens a lecture at the second the professor writes the formula.
- A teaching video generated from the course itself for every one of its 19 concepts, with
  no scene dropped by the grounding check and 99 % of 77 narration lines judged fully
  supported by the source on screen.
- A measured evaluation with its failures left in. RAGAS on 39 questions with known source
  locations: faithfulness 0.96, answer relevancy 0.91, context precision 0.92, context
  recall 1.00 (0.77 with vision switched off). All 14 off-material questions declined and
  none of the 39 course questions declined by mistake. 98 % of 58 cited sentences fully
  supported by the passage they cite, by a judge that calls 0 % supported when the passages
  are swapped. And 720
  simulated students, with an ablation that shows where adaptivity stops helping.
- No build step, no Docker, no office suite: `make setup && make serve`.

## What we learned

That "multimodal" is not a feature to add at the end. For this course it was the difference
between having the content and not having it. And that an evaluation is most useful when it
embarrasses you early.

## What's next for Pramana

Lesson narration in Hindi; fit the learner model's parameters to real answer logs; estimate each student's own pace
and memory (our first attempt could not tell students apart and was removed); a second
course in a different subject; a stronger, independent judge for the evaluation.
