# The learner model

Per student and per concept, Pramana keeps one number: the probability that the concept is
mastered. It is updated after every quiz answer and every conversation, it decays with
time, and it is tied to the other concepts through the prerequisite map. The code is
`pramana/learner.py`, about 300 lines with no dependencies.

## Update rule

The base is Bayesian Knowledge Tracing. For belief `p` and an answer scored `s ∈ [0, 1]`:

```
right = p(1 − slip) / [p(1 − slip) + (1 − p)·guess]
wrong = p·slip / [p·slip + (1 − p)(1 − guess)]
posterior = s·right + (1 − s)·wrong          # partial credit is soft evidence
learned   = posterior + (1 − posterior)·learn
p'        = learned            if s > 0
            min(p, learned)    if s = 0      # a wrong answer never raises the estimate
```

Three departures from textbook BKT, each for a stated reason:

**Slip and guess depend on the item.** `guess` is luck plus partial knowledge:

```
guess = chance + (1 − chance) · partial(difficulty)
chance  = 0.25 MCQ · 0.05 short answer · 0.03 numerical
partial = 0.35, 0.20, 0.10, 0.03, 0.00 for difficulty 1 … 5
```

A student who has not mastered a concept can still recall its definition, so an easy item is
answered correctly without mastery far more often than chance alone suggests; a hard
numerical item almost never is. `slip` rises from 10 % on a difficulty-1 item to 26 % on a
difficulty-5 item. Together these make a correct answer to a hard numerical problem much
stronger evidence than a correct answer to an easy MCQ: in a quiz, from the prior of
25 %, a difficulty-4 numerical answer moves belief to 84 % and a difficulty-1 MCQ to 46 %. This is the idea behind item response
theory, expressed through BKT's two emission parameters instead of a separate model.

**The learning step depends on where the answer came from, and cannot reward a miss.**
Classic BKT adds `learn` after every attempt, which lets a wrong answer raise a low estimate.
A student who sees "Not correct: mastery 11 % → 12 %" is right to distrust the model. Here a
quiz answer with feedback adds a learning step of 0.15 and a graded chat reply half of that,
and after a wrong answer the result is capped at the belief before it. A diagnostic answer
adds none: the diagnostic is a measurement, and it gives no feedback until the end.

**Forgetting.** Belief stored at time `t₀` is read at time `t` as

```
p(t) = floor + (p − floor)·exp(−(t − t₀) / τ),   τ = 7 days × (1 + 0.7 × successful recalls)
```

Each successful recall lengthens the time constant, which is the spaced-repetition effect.
The decayed value is what the tutor, the question selector and the schedule read. The
dashboard shows both: the solid bar is belief now, the dashed mark is belief before
forgetting.

## Evidence along the map

* **Success credits prerequisites.** A correct answer on a concept is evidence that what it
  rests on is in place. Each direct prerequisite is pulled half of the way towards the
  belief just earned, the ones behind it a quarter, then an eighth, and so on down the
  chain. A prerequisite already believed stronger is left alone.
* **Failure caps what is unobserved downstream.** After a miss, a concept that depends on
  this one and has never been observed cannot be believed more than 0.15 above it. This is
  what makes a ten-question diagnostic place a student across a whole course.
* **Root cause.** For a weak concept the model searches the prerequisite chain for the
  weakest link below 50 %. Reports and the tutor point there first ("this rests on X, which
  is not secure yet").

These inferred updates are logged with source `inferred` and never counted as observations.

## Evidence from conversation

A chat message is weaker evidence than a graded answer, so it moves belief less.

* Each message is read by a small model for signals about the student: `understood`,
  `confused`, or `misconception`, each tied to a concept. A signal is a soft update with
  weight 0.35.
* When the tutor ends an explanation with a check question, the next message is graded
  against the expected answer (correct, partial, incorrect) and applied with weight 0.8.

The tutor reads the model back: for the concepts a question touches it is told whether the
student is weak, developing or has mastered them, which prerequisite is shaky, and which
mistaken beliefs they have shown recently. A weak student gets a step-by-step explanation
that starts from the prerequisite; a strong one gets a short answer that points forward.

## Cold start

A new student has belief 0.25 everywhere and no observations. The diagnostic chooses in two
steps. First the concept: the one where belief is closest to 50 %, weighted by how many
concepts it is connected to in the map, because its answer moves them too (a miss rules out
what is built on it, a hit lifts what it rests on). Then the item: among that concept's
multiple-choice and numerical questions, the one whose answer carries the most information
about mastery,

```
I(mastery; answer) = H(P(correct)) − [p·H(slip) + (1 − p)·H(guess)]
```

which prefers hard, hard-to-guess items over easy recall. The intake conversation works too:
say what you find hard and the signals above start the model.

## Choosing the next question

`pramana/assess/select.py`:

```
priority(concept) = 0.70 · (1 − mastery) · readiness
                  + 0.10 · 1/(1 + observations)
                  + 0.20 · min(1, 4 · mastery lost to forgetting)

readiness = Π over direct prerequisites of clamp(mastery / 0.80, 0.15, 1)²
```

A prerequisite believed at 50 % is a coin flip, not a foundation, so it cuts readiness to
0.39; two such prerequisites cut it to 0.15. The student is then not drilled on a concept
they are not ready for, and the prerequisite itself has the higher priority. Each time a
concept is asked within one sitting its priority is multiplied by 0.75, which spreads the
sitting. Within the chosen concept the selector takes the unseen item whose predicted chance
of a correct answer is closest to 85 % (Wilson et al., 2019). An attempted question is never
served again, and a candidate with cosine similarity of 0.88 or more to anything the student
has seen is skipped.

## Every number is explained

Each update writes a row to `evidence` with the belief before and after, the source (quiz,
diagnostic, chat, inferred) and the detail (the question, the misconception, the concept it
was inferred from). The Progress page lists them. Nothing about a student's estimate is
hidden from the student.

## Parameters

| Constant | Value | Meaning |
|---|---|---|
| `PRIOR` | 0.25 | belief before any evidence |
| `LEARN` | 0.15 | chance a quiz attempt with feedback turns "not yet" into "mastered" (half for chat, none for the diagnostic) |
| `FLOOR` | 0.10 | where an unreviewed concept decays to |
| `TAU_DAYS`, `TAU_GROWTH` | 7, 0.7 | forgetting time constant and its growth per successful recall |
| `PREREQ_SHARE` | 0.50 | how far a success pulls a direct prerequisite towards the belief it earned; halves with each further step |
| `PREREQ_HEADROOM` | 0.15 | how far an unobserved concept may sit above a failed prerequisite |
| `READY_AT`, `READY_POWER` | 0.80, 2 | belief at which a prerequisite stops holding a concept back, and how steeply a weaker one does |
| `CHANCE` | 0.25 / 0.05 / 0.03 | right by luck alone: MCQ, short answer, numerical |
| `PARTIAL` | 0.35 … 0.00 | share of non-masters who can still do an item of difficulty 1 … 5 |
| `MASTERED`, `WEAK` | 0.80, 0.50 | level thresholds |

These were set by reasoning and by the simulation, not fitted to real students. The
simulation changed several of them: the first version of the adaptive policy lost to plain
syllabus order, and the difficulty-aware guess, the stricter readiness and the
information-based diagnostic are what that failure led to ([evaluation.md](evaluation.md)
has the comparison, including the profile where syllabus order still wins). With real
answer logs the slip, guess and learning parameters should be fitted per concept (EM, as in
standard BKT) and the forgetting constants per student. That is the first thing to do with
real data.

## Known limits

* One number per concept cannot represent "knows the definition, cannot apply it".
  Difficulty-aware slip softens this but does not remove it.
* The model assumes the concept tags on questions are right. A mis-tagged question teaches
  it something false about the wrong concept.
* Conversation signals depend on a small model's reading of a message and can be wrong;
  that is why their weight is low and every one is shown in the evidence log.
* Validation so far is on simulated students ([evaluation.md](evaluation.md)). The simulator
  uses a different response model from the estimator, but it is still a simulator.
