# Grounding: how an answer stays tied to its source

The promise is narrow and checkable: **every sentence the tutor presents as coming from your
course names the page, slide or lecture moment it came from, and when the material does not
cover a question the tutor says so instead of answering from memory.**

The promise is kept by structure and by code, not by asking a model to behave.

## One turn, four steps

1. **Understand** (small model). The message is rewritten as a standalone English search
   query (so "and what about the second one?" and questions typed in Hindi both retrieve
   properly), its intent is classified, and it is read as evidence about the student
   (see [learner-model.md](learner-model.md)).
2. **Retrieve** (local, no model call). BM25 and dense search are fused by reciprocal rank
   and the top 24 candidates are re-ranked by a cross-encoder; the best six go forward. A
   spoken passage and the board reading from the same moment travel together. If the
   student is weak on a prerequisite of what they asked about, that prerequisite's best
   passage is added and marked, so the explanation can start where the student is.
3. **Answer** (tutor model). The reply is requested as JSON:

   ```json
   {
     "coverage": "covered | partial | not_covered",
     "segments": [{"text": "one to three sentences", "sources": ["S2", "S5"]}],
     "missing": "what the material does not address",
     "outside": "",
     "check_question": "...", "check_answer": "...", "check_concept": "..."
   }
   ```

   The model cannot return free prose. An answer exists only as segments, and a segment
   exists only with the ids of the excerpts that support it.
4. **Enforce** (code). `tutor.respond` then applies rules the model cannot override:
   * a segment whose source ids are missing or invalid is **removed** from the answer, and
     the removal is counted (`unsourced_segments_removed`);
   * if no segment survives, coverage becomes `not_covered` whatever the model claimed;
   * `outside` is discarded unless the student switched on *Allow outside knowledge* **and**
     coverage is not `covered`.

## Declining

There are two gates, because off-material questions come in two kinds.

* **Nothing retrieved is about the question.** If the best cross-encoder score is below a
  threshold, the tutor declines without calling the answer model at all. This catches
  questions from another subject ("how does a transformer network work?") cheaply and with
  no chance of a fluent wrong answer.
* **Something related was retrieved, but it does not contain the answer.** A question on
  rotational inertia retrieves passages about inertia and mass. Here the answer model
  decides, with the instruction that being on a related subject is not coverage. This is
  the harder case and the one the evaluation watches most closely.

A declined question is not a dead end: the reply lists the nearest material that does exist.

## Outside knowledge, kept separate

By default nothing from outside the excerpts may appear anywhere. With *Allow outside
knowledge* on, a partly covered or uncovered question gets a second block under the label
**Not from your course material**, in a different colour, with no citation numbers. Sourced
and unsourced content are never mixed in one paragraph.

## What a citation carries

A citation is a unit plus the excerpt of that unit closest to the sentence it supports.
Opening it shows the original artefact, not a text dump: the textbook page with the passage
outlined, the slide, or the video seeked to the moment. Beside it is the panel *What
Pramana read here*, which shows the text the system extracted from that place, including
what vision restored. If the extraction was wrong, the student can see that it was.

## How this is measured

`evaluation/grounding.py` runs the tutor over a test set and reports:

* a refusal confusion matrix over in-material and off-material questions, with "another
  subject" and "physics the chapters do not teach" reported separately;
* whether answers cite the known gold location (strict: the same fact cited from another
  source counts as a miss);
* citation support: a different model reads each answer segment next to the excerpts it
  cites and judges whether they state it.

RAGAS faithfulness is computed on the same answers. Results are in
[evaluation.md](evaluation.md).

## Known limits

* Enforcement guarantees that every segment *has* a source, not that the source *entails*
  it. A model can cite a real excerpt for a claim the excerpt only partly makes. The
  citation-support metric measures how often that happens; it is not zero.
* The excerpt shown under a citation is chosen by word overlap with the sentence. For an
  answer written in Hindi the overlap is weak and the excerpt may be the start of the unit
  rather than the best sentence. The page and highlight are still exact.
* The refusal threshold of the first gate was set on the evaluation's own off-material
  questions. It is a conservative value (far below any in-material score), but it has not
  been validated on a second course.
