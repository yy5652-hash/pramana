# Lessons

A lesson is a short narrated film on one concept, made for one student, and cut entirely
from that student's own course: the textbook page with the passage outlined and the quoted
words lit, the slide, the lecture at the second it was said. It is the tutor's rule applied
to video: the narrator may say only what a source says, and the source is what is on screen.

```
pramana lesson mechanics --student Asha            # the concept the learner model recommends
pramana lesson mechanics --concept friction-forces
```

or the **Lessons** page of the app. A lesson of about a minute takes one to two minutes to
make on a laptop; the result is an ordinary MP4 (1280×720, H.264 + AAC) that can be
downloaded.

## What happens

| Step | Where | What it does |
|---|---|---|
| Which concept | `script.next_concept` | The concept with the highest priority in the learner model: the weakest one the student is ready for, or one that is fading. The student can pick another. |
| Which sources | `script.material` | Retrieval restricted to units tagged with the concept, a few of each kind: textbook passages, a figure, slides, one lecture passage and the board reading that goes with it. If a prerequisite is shaky, one passage from it is put first. |
| The script | `script.write` | One model call. It is told the student's level on the concept, the shaky prerequisite and any misconception the student has shown in practice, and writes four to six scenes: a source, what the narrator says over it, and the words of the source the narration rests on. One scene may be the lecturer's own voice instead of the narrator's. |
| Grounding, by code | `script._grounded` | A scene is kept only if it names a source it was given, uses it once, and has something to say. Words to be lit on a page must be found in that passage, word for word. A stretch of lecture to be heard must be found in the word-level transcript, which also gives its start and end. Anything else is dropped; with fewer than three scenes left, no lesson is made. |
| Pictures | `build.py` | The PDF page is rendered again at three times its size, so a close-up is sharp. The passage's true extent on the page and the printed position of the quoted words are looked up in the PDF itself. Lecture scenes are decoded from the lecture video. |
| Voice | `voice.py` | Kokoro-82M through ONNX Runtime, on this machine. The model (about 120 MB) is downloaded on first use. Each line is cached. |
| The cut | `render.py` | Pillow draws each frame, PyAV encodes. A still gets a slow camera move and the outlined passage; a lecture scene plays under the narrator, or with the lecturer's own voice and subtitles made from the transcript. Every scene carries its source in the corner and a caption. |

The storyboard is stored with the lesson. Beside the player, the app lists every scene with
the source it shows, and clicking a source opens it at the page, slide or second, exactly as
a citation in the tutor does.

## How it is personal

* **The concept** comes from the learner model unless the student chooses.
* **The opening** recalls the prerequisite when the model says it is not secure.
* **The pace and emphasis** follow the student's level on the concept (new, struggling, half
  there, mostly mastered).
* **Misconceptions** the student has shown in practice are passed to the script writer, to
  be addressed if a source speaks to them.
* **The ending** sends the student to the checked questions on that concept.

## What it does not do

* It generates no pictures. Nothing in a lesson is drawn by a model: every frame of a scene
  is a page, a slide or a lecture frame from the course. A course without lecture video
  gets lessons without the lecturer.
* The narration is checked by code only as far as "this scene shows the source it cites".
  Whether each spoken sentence is supported by that source is a judgement, and it is
  measured with the same judge as the tutor's citations (see `results.md`), not guaranteed.
* Narration is English. The tutor answers in Hindi and Hinglish; the lesson narrator does
  not yet.
* Formulas are spoken in words and shown as the source prints them. The film has no
  typesetting of its own.
* A lesson is a film of one to two minutes on one concept, not a lecture.

## Why it is built this way

Systems that generate teaching videos from a prompt usually have a model write animation
code (Manim) or assemble stock footage. Both produce pictures that come from nowhere the
student can check, and the first needs a strong coding model and a TeX toolchain. A course
already contains its own pictures. Cutting the lesson from them keeps the product's one
promise, costs one small model call, and runs with the dependencies the rest of the system
already has, plus a local voice.

Ideas taken from elsewhere, with thanks: narration timed first and pictures cut to it
(ManimCommunity/manim-voiceover); a pointer that lands on the part of the page being
spoken about (showlab/Paper2Video), done here with the PDF's own character positions
instead of a vision model. No code from either is used.
