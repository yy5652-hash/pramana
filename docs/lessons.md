# Lessons

A lesson is a narrated film of about two minutes on one concept, made for one student, and
cut entirely from that student's own course: the textbook page with the passage outlined and
the quoted words lit, the slide, the lecture at the second it was said. It is the tutor's
rule applied to video: the narrator may say only what a source says, and the source is what
is on screen.

```
pramana lesson mechanics --student Asha            # the concept the learner model recommends
pramana lesson mechanics --concept friction-forces
```

or the **Lessons** page of the app. A lesson takes about half a minute to make
on a laptop; the result is an ordinary MP4 (1280×720, H.264 + AAC) that can be downloaded.

## The arc of a lesson

| Part | What is on screen | Where it comes from |
|---|---|---|
| The idea and the rule | Textbook passages with the quoted words lit, a figure, a slide | Retrieval restricted to units tagged with the concept |
| How the lecturer puts it | A stretch of the lecture, in the lecturer's own voice, with subtitles | The word-level transcript |
| A worked example | The textbook's own example, one step at a time: the problem, the strategy, the solution, what the answer means | The textbook prints its examples in that pattern, and ingestion kept the parts |
| A mistake | The question, the wrong answer, the right one and the slip, set as a card | The student's own latest wrong answer on this concept; if they have none, a wrong answer the question bank marks as a common one |
| What to keep | Two or three points, each with the number of the source it rests on | Written by the script on the scene whose source states them; a point goes if its scene is dropped |
| One question | A checked question the student has not met, near the success rate practice aims for | The question bank; the answer is not shown, it is waiting in Practice |

## What happens

| Step | Where | What it does |
|---|---|---|
| Which concept | `script.next_concept` | The concept with the highest priority in the learner model: the weakest one the student is ready for, or one that is fading. The student can pick another. |
| Which sources | `script.material` | A few units of each kind: textbook passages, a figure, slides, one lecture passage and the board reading that goes with it. If a prerequisite is shaky, one passage from it is put first. |
| Which example | `script.worked_example` | The textbook example whose parts are tagged most strongly with the concept; the earliest wins a tie. |
| Which mistake | `script.mistake` | The student's latest wrong multiple-choice or numerical answer on the concept, with the slip the grader named. Otherwise a distractor of a checked question, with the misconception it was written to catch. |
| The script | `script.write` | One model call. It is told the student's level on the concept and the shaky prerequisite, and writes the teaching scenes, one step for each part of the example, two or three sentences about the mistake, and, on the three scenes that carry them, the points to keep. |
| Grounding, by code | `script._grounded`, `script._steps` | A scene is kept only if it names a source it was given, uses it once, and has something to say. Words to be lit on a page must be found in that passage, word for word. A stretch of lecture to be heard must be found in the word-level transcript. The steps of the example must come in the textbook's order, and without the solution there is no example. A point of the recap is written on a scene or a step and is dropped with it. With fewer than three teaching scenes left, no lesson is made. |
| Which question | `script.check_question` | From the bank, never one the student has attempted or one close to it. |
| Pictures | `build.py` | The PDF page is rendered again at three times its size, so a close-up is sharp. The passage's true extent on the page and the printed position of the quoted words are looked up in the PDF itself. Lecture scenes are decoded from the lecture video. |
| Type | `typeset.py` | The cards (the mistake, the points, the question) hold formulas. They are set with the KaTeX fonts the app already ships, for the part of LaTeX the question bank uses: fractions, scripts, vectors, roots. No TeX is installed or called. |
| Voice | `voice.py` | Kokoro-82M through ONNX Runtime, on this machine. The model (about 120 MB) is downloaded on first use. Each line is cached. |
| The cut | `render.py` | Pillow draws each frame, PyAV encodes. A still gets a slow camera move and the outlined passage; a lecture scene plays under the narrator, or with the lecturer's own voice; a card builds up line by line as it is spoken. Every scene carries its source in the corner and a caption. |

The storyboard is stored with the lesson. Beside the player, the app lists every scene with
the source it shows, and clicking a source opens it at the page, slide or second, exactly as
a citation in the tutor does. The points to keep and the closing question are listed there too.

## How it is personal

* **The concept** comes from the learner model unless the student chooses.
* **The opening** recalls the prerequisite when the model says it is not secure.
* **The pace and emphasis** follow the student's level on the concept (new, struggling, half
  there, mostly mastered).
* **The mistake** is the student's own: what they answered, what the key is, and the slip the
  grader recognised (a factor of two, a sign, a unit conversion, or the misconception behind
  the option they chose).
* **The closing question** is one they have not seen, at the difficulty the learner model
  would give them next.

## What it does not do

* It generates no pictures. Nothing in a lesson is drawn by a model: every frame of a scene
  is a page, a slide or a lecture frame from the course, or a card of type whose words come
  from the question bank. A course without lecture video gets lessons without the lecturer.
* The narration is checked by code only as far as "this scene shows the source it cites".
  Whether each spoken sentence is supported by that source is a judgement, and it is
  measured with the same judge as the tutor's citations (see `results.md`), not guaranteed.
* Narration is English. The tutor answers in Hindi and Hinglish; the lesson narrator does
  not yet.
* The worked example is the textbook's, not a new one made for the student. A concept the
  textbook gives no example for gets a lesson without that part.
* The typesetting covers what the question bank uses, not LaTeX. A command it does not know
  is shown by name.
* A lesson is a film of about two minutes on one concept, not a lecture.

## Why it is built this way

Systems that generate teaching videos from a prompt usually have a model write animation
code (Manim) or assemble stock footage. Both produce pictures that come from nowhere the
student can check, and the first needs a strong coding model and a TeX toolchain. A course
already contains its own pictures, and its own worked examples. Cutting the lesson from them
keeps the product's one promise, costs one small model call, and runs with the dependencies
the rest of the system already has, plus a local voice.

Ideas taken from elsewhere, with thanks: narration timed first and pictures cut to it
(ManimCommunity/manim-voiceover); a pointer that lands on the part of the page being
spoken about (showlab/Paper2Video), done here with the PDF's own character positions
instead of a vision model. No code from either is used.
