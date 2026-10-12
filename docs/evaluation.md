# Evaluation: what was measured, and how

The numbers are in [results.md](results.md), which is generated from
`evaluation/results/*.json`. This page says how each number is produced, what it does and
does not show, and what went wrong along the way.

Everything here runs with `make eval`. With `PRAMANA_LLM_MODE=replay` it re-runs from the
committed response cache without an API key and gives the same numbers.

## 1. The test set

`evaluation/testset.jsonl`: 39 questions whose answers have a **known location** in the
sources, and 14 that the material does not cover.

**In-material questions.** Units were sampled by how they were obtained, so every modality
is tested: textbook prose, textbook passages whose maths had to be restored by vision,
textbook figures, slides, spoken lecture passages, and readings of the board. For each
sampled unit a model drafted a question a student might ask and a reference answer, both
resting on that unit alone (`evaluation/build_testset.py`). The gold location is the unit's
page, slide or time window.

The drafts were then checked one by one against their source passages, by Claude Code (the
AI coding assistant that built this project), not by a person.
`evaluation/testset.curation.json` records what changed: 2 of 35 drafts were dropped (one
reference restated its question; one question only made sense inside its lecture), and 6
figure questions were written directly, without the drafting model, because it had marked
all but one sampled figure as unusable.

**Off-material questions** were written directly as well. Six are from other subjects (transformers,
the capital of Australia, mRNA vaccines). Eight are physics that the four ingested chapters
do not teach (moment of inertia, Bernoulli's equation, time dilation, Kepler's third law).
The second group is the hard one: retrieval finds passages that sound related.

**What this test set is not.** No human expert wrote or reviewed it. It is small (53 questions), from one course, and its
in-material questions were drafted from the very passages they are scored against, which
makes them easier to retrieve than a real student's question. Every interval in
`results.md` is a normal approximation on about 40 points; treat differences smaller than
about 0.15 as noise.

## 2. Retrieval (no model involved)

`evaluation/retrieval.py`. For each in-material question, the rank at which a result sits
at the gold location. Reported for the full pipeline and for three ablations (no
re-ranking, dense only, lexical only), and for a knowledge base built without vision.

The match is strict. The same fact is often stated in the textbook, on a slide and in a
lecture; retrieving it from one of the other two counts as a miss. This is why the
"lecture-board" row is low: a question about the definition of instantaneous acceleration
is answered equally well by the textbook, and the textbook usually ranks first.

**A finding that did not go the way I expected.** The knowledge base built without vision
scores almost the same on this metric. The reason is the metric, not the pipeline: a
no-vision unit from the right *page* counts as a hit even when the equation the question
asks for is missing from it. Location recall cannot see missing content. The content-level
comparison is the RAGAS context-recall row in `results.md`, computed on both knowledge
bases (`evaluation/ablation.py`).

**How to read that context recall.** The reference answers were written from passages of
the full knowledge base, so with vision the retrieved text can be expected to contain
nearly every claim, even when the exact gold passage is not retrieved, because the same
formula is usually stated in more than one place. A score close to 1 there is a ceiling
set by how the test set was built, not a discovery. The informative number is how far the
text-only knowledge base falls below it, and in which rows: prose, slides and speech keep
their score; formulas, figures and the board do not.

## 3. Grounding

`evaluation/grounding.py` runs the tutor on all 53 questions (no student history, no
conversation context) and saves the answers and their retrieved contexts.

* **Refusal.** A 2 × 2 table of answered/declined against in/off material, with the two
  kinds of off-material question reported separately.
* **Citation location.** The share of answers that cite the gold location. Strict, as above.
* **Citation support.** Each answer segment is shown to a *different* model next to the
  excerpts it cites, and judged fully supported, partly supported or unsupported. This
  measures what enforcement cannot guarantee: code ensures every segment has a source, not
  that the source says it.
* **A check on the judge.** A judge that agrees with everything proves nothing, so the same
  segments are shown to it a second time next to the excerpts that a *different* answer
  cites. The share it still calls supported is reported beside the real result. It is not
  expected to be zero: a course repeats itself, and a sentence about Newton's second law
  can be supported by a passage another answer cited.

## 4. Answer quality with RAGAS

`evaluation/ragas_eval.py` scores the same saved answers with RAGAS, as published:
faithfulness, answer relevancy, context precision (with reference) and context recall.

Two adapters connect RAGAS to this project. `ReplayableLLM` sends the judge's prompts
through Pramana's own client, which makes the run cacheable and replayable; `LocalEmbeddings`
gives RAGAS the embedding model retrieval uses. The metric definitions and prompts are
RAGAS's own.

The judge (`PRAMANA_JUDGE_MODELS`, by default `gemini-3.1-flash-lite`) is not the model that
writes the tutor's answers (`gemini-3.5-flash-lite`), so no model marks its own work. It is
still a small model from the same provider. A stronger judge from another provider would be
better; the free tier this was built on allows about twenty requests a day to the larger
models, and a RAGAS run needs several hundred.

## 5. Personalisation, with simulated students

`evaluation/simulate.py`. No language model is called; it runs in under a minute.

**The simulated student.** A hidden proficiency in [0, 1] per concept. The chance of a
correct answer is a logistic curve in (proficiency − item difficulty) with a guessing floor
by question type. Each answered question raises proficiency; a day passes between sessions
and proficiency decays towards a floor. Six profiles: novice, strong start and weak finish,
prerequisite gap, advanced, fast learner, forgetful.

**Three policies** work through the real question bank for seven daily sessions of eight
questions, using the app's own selector and learner-model code:

* *adaptive*: a diagnostic first session, then prerequisite-aware selection;
* *syllabus order*: concepts in order, easiest unseen question first, no learner model;
* *random*: unseen questions drawn uniformly.

**Two guards against grading the model on its own assumptions.**

1. The simulator's response model is not the learner model's. The estimator is BKT with a
   binary "mastered" state; the simulated student has a continuous proficiency and a
   logistic response curve.
2. Two assumptions in the simulator favour any prerequisite-aware, difficulty-matched
   policy: a student learns less from a question whose prerequisites they lack, and less
   from one far too easy or too hard. Both are standard, and both are assumptions. So every
   result is also reported for a **flat learner** with both switched off, where sequencing
   cannot help by construction.

**Reported.** Gain in mean true proficiency by the day after the last session; how well the
learner model knows the student (error of its predicted success on a fixed probe item
against the truth, after the first and the last session, with a no-model baseline; overlap
of the five weakest concepts, estimated against true); and the share of served questions
the student had seen before.

### What the simulation changed

The first run was a failure worth recording. The adaptive policy beat random but lost
clearly to plain syllabus order (+0.093 against +0.115), and its model of the student did
not improve with data. Tracing individual students showed why:

* A single correct answer to an easy MCQ moved "mastery" from 25 % to about 60 %. The model
  then served difficulty-4 questions to a student who had recalled one definition. Fix:
  non-masters can answer easy items from partial knowledge, so the guess parameter now
  depends on difficulty, not only on question type.
* A wrong answer collapsed belief to 3 %, and the policy kept returning to that concept
  while the simulated student had in fact learned from the feedback. Fix: an attempt with
  feedback now carries a learning step whatever its score, capped so a wrong answer can
  hold belief where it was but never raise it.
* The diagnostic asked easy questions, which reveal little. Fix: it now picks the item with
  the highest expected information about mastery (mutual information), which favours hard,
  hard-to-guess items.
* A belief of 0.5 in a prerequisite was treated as "ready". Fix: readiness now requires a
  mastered prerequisite and falls off steeply below that.
* Practice items now aim at an 85 % predicted success rate rather than 70 %.

One idea was tried and removed: two per-student factors (learning pace, memory) estimated
from prediction residuals. They improved tracking slightly but could not tell the fast
learner or the forgetful student from the others, so they were not explaining what they
claimed to. They are not in the code.

### What the simulation shows now, including where the product loses

See the tables in `results.md`. In words:

* Adaptive practice teaches clearly more than random practice.
* Against syllabus order it is about level overall. It wins for the students adaptivity is
  meant for (novices, and students with a gap in their prerequisites) and **loses for the
  fast learner**, who is best served by simply moving on after each question; the model's
  fixed learning rate holds that student back.
* In the flat learner, where prerequisites and difficulty do not matter, syllabus order is
  best. That is the expected result of the ablation, and it bounds the claim: the adaptive
  policy helps to the extent that prerequisite structure matters for learning.
* The adaptive policy's model of the student is the most accurate of the three and gets
  more accurate with every session.
* No policy ever served a question twice.

These are simulated students. The result says the machinery behaves sensibly under stated
assumptions; it does not say real students learn more. That needs real students.

## 6. Lessons

`evaluation/lessons.py`. A storyboard is written for every concept of the course, for a new
student. No film is cut; the picture adds nothing to what is measured here.

* **What the code let through.** Scenes kept and scenes dropped (a source that does not
  exist, a source used twice, words to be heard that the lecture does not contain), and how
  many textbook scenes had their quoted words found in the passage word for word. Only
  those are lit on the page; the others are shown without a highlight.
* **Whether the narration is supported.** Code can check that a scene shows the source it
  cites. It cannot check that the narrator's sentence is what that source says. So each
  narrated line is read by the judge next to the text of the source it is spoken over, with
  the same three verdicts as the tutor's citations. The judge is not the model that wrote
  the script.
* **What is not measured.** Whether a lesson teaches. That needs students, or at least a
  before-and-after test with a model that does not already know mechanics, and neither was
  available.

## 7. Limits of the whole evaluation

* One course, one subject, one language of instruction.
* The test set is small and partly model-drafted (section 1).
* The RAGAS judge and the citation judge are one small model from the tutor's own provider
  (a different model from the tutor's, but not an independent one).
* Question correctness is checked by a second model and by arithmetic, not by a physicist.
  A numerical item whose formula is wrong in a way that still reproduces its own key
  passes the arithmetic check; only the blind solve can catch it.
* No real students have used the system.
