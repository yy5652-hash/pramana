// The film's clock. Every duration and every narration cue is derived here from the marks the
// real takes recorded, so re-recording a take re-times the film. No JSX and no Remotion in
// this file: tools/timeline.mjs imports it directly to place the narration and write the SRT.
import ask from "../public/takes/ask.json" with { type: "json" };
import lessons from "../public/takes/lessons.json" with { type: "json" };
import film from "../public/data/film.json" with { type: "json" };
import hinglish from "../public/takes/hinglish.json" with { type: "json" };
import map from "../public/takes/map.json" with { type: "json" };
import practice from "../public/takes/practice.json" with { type: "json" };
import progress from "../public/takes/progress.json" with { type: "json" };
import refuse from "../public/takes/refuse.json" with { type: "json" };

export const FPS = 30;
type Marks = { marks: { t: number; label: string; rect?: number[]; misconception?: string; text?: string }[] };
const all = (take: Marks, label: string) => take.marks.filter((m) => m.label === label).map((m) => m.t);
const one = (take: Marks, label: string) => all(take, label)[0];

// ---- S4: the question, the numbers, the cut to the lecture --------------------------------
const TRIM = 1.0;                                       // the idle first second of the take
const s4 = (label: string) => one(ask, label) - TRIM;   // seconds into the shot
export const S4 = {
  trim: TRIM,
  typed: s4("typed"), asked: s4("asked"), answered: s4("answered"), page: s4("page-open"), video: s4("video-open"), play: s4("video-play"),
  cut: s4("video-play") + 4.2,           // leave the app's player for the lecture itself
  passageStart: 178.0,                   // source second at which the cited passage begins (2:58)
  footage: 11.3,                         // seconds of lecture after the cut: he finishes F = dp/dt at about 3:13
  hold: 5.0,
};
export const S4_SECONDS = S4.cut + S4.footage + S4.hold;

// ---- S6: two questions it declines --------------------------------------------------------
const [typed1, typed2] = all(refuse, "typed");
const [asked1, asked2] = all(refuse, "asked");
const [answered1, answered2] = all(refuse, "answered");
export const S6_CLIPS = [
  { name: "refuse", from: typed1 - 4.3, to: asked1 + 0.35 },
  { name: "refuse", from: answered1 + 0.2, to: answered1 + 3.3 },
  { name: "refuse", from: typed2 - 2.6, to: asked2 + 0.35 },
  { name: "refuse", from: answered2 + 0.2, to: answered2 + 4.4 },
  // then a question the course does cover, asked in Hinglish: its last words, and the answer
  { name: "hinglish", from: one(hinglish, "typed") - 1.3, to: one(hinglish, "answered") + 4.9 },
];
/** Where the Hinglish answer sat on screen (take pixels), recorded by the take. */
export const S6_ANSWER = (hinglish as Marks).marks.find((m) => m.label === "answer")?.rect;

// ---- S7: questions, misconceptions, the learner model -------------------------------------
// The wrong answer the film shows is the first one whose feedback names a misconception.
const wrongs = (practice as Marks).marks.filter((m) => m.label === "feedback-wrong");
const wrong = (wrongs.find((m) => m.misconception) ?? wrongs[0]).t;
const node = one(map, "node");
const plan = one(progress, "plan");
export const S7_CLIPS = [
  { name: "practice", from: wrong - 4.4, to: wrong + 7.4 },
  { name: "map", from: Math.max(0.6, node - 2.6), to: node + 6.6 },
  { name: "progress", from: 1.2, to: 7.4 },
  { name: "progress", from: plan + 0.5, to: plan + 6.3 },
];
export const S7_WRONG = 4.4;                             // seconds into the shot at which the wrong answer is marked
// Where the question, the verdict and the cited source were on screen after that wrong answer
// (take pixels), recorded by the take itself. The camera in S7 is aimed from these.
const rectAfter = (label: string) => (practice as Marks).marks.find((m) => m.label === label && m.t > wrong && m.rect)?.rect;
export const S7_FOCUS = { question: rectAfter("question"), verdict: rectAfter("verdict"), meter: rectAfter("meter"), source: rectAfter("source") };
/** What the mastery meter read after that answer, e.g. "25% → 7%". */
export const S7_SHIFT = (practice as Marks).marks.find((m) => m.label === "meter" && m.t > wrong)?.text ?? "";

// ---- S7b: the app cuts a lesson, and the lesson itself --------------------------------------
// Two pieces of the take (asking for the lesson; the finished lesson playing in the app), then
// the lesson film on its own, from the scene in which the lecturer speaks.
const lesson = (lessons as unknown as { lesson: { concept: string; seconds: number; scenes: { kind: string; at: number; seconds: number }[] } }).lesson;
const heard = lesson.scenes.find((scene) => scene.kind === "listen") ?? lesson.scenes.find((scene) => scene.kind === "read")!;
export const S7B = {
  clips: [{ name: "lessons", from: one(lessons, "cut") - 2.4, to: one(lessons, "cut") + 2.6 }, { name: "lessons", from: one(lessons, "play") - 0.5, to: one(lessons, "play") + 4.3 }],
  movieFrom: heard.at + 0.25,                                    // seconds into the lesson film
  movieSeconds: Math.min(heard.seconds - 0.6, 7.4),
  lecturer: heard.kind === "listen",
  made: one(lessons, "made") - one(lessons, "cut"),               // how long the app took to cut it, measured in the take
  concept: lesson.concept,
  lessonSeconds: lesson.seconds,
};

// ---- S8: the ledger of measurements, then the simulated students ----------------------------
// A row of the ledger exists only if its result file does, so the schedule is built from what
// was measured: each group of rows arrives with the narration line that speaks of it.
const measured = (film as unknown as { results: Record<string, unknown> }).results;
const rowsAt: Record<string, number> = { retrieval: 2.2 };
const s8cues: { line: string; at: number }[] = [{ line: "s8a", at: 0.5 }, { line: "s8b", at: 1.9 }];
let s8clock = 10.8;                                      // s8b has finished
if (measured.ragas) {
  s8cues.push({ line: "s8r", at: s8clock });
  Object.assign(rowsAt, { faithfulness: s8clock + 0.3, relevancy: s8clock + 2.6, precision: s8clock + 4.2 });
  s8clock += 6.9;
}
if (measured.ablation) {
  s8cues.push({ line: "s8c", at: s8clock });
  rowsAt.recall = s8clock;
  s8clock += 4.5;
}
if (measured.grounding) {
  s8cues.push({ line: "s8g", at: s8clock });
  Object.assign(rowsAt, { declined: s8clock + 0.2, supported: s8clock + 4.3 });
  s8clock += 8.9;
}
const students = s8clock + 0.3;
s8cues.push({ line: "s8d", at: students + 0.4 }, { line: "s8e", at: students + 13.4 });
export const S8 = { at: rowsAt, students, close: students + 13.4, seconds: students + 20.0, cues: s8cues };

const span = (clips: { from: number; to: number }[]) => clips.reduce((t, c) => t + Math.round((c.to - c.from) * FPS), 0) / FPS + 0.2;
const starts = (clips: { from: number; to: number }[]) => clips.reduce<number[]>((acc, c, i) => [...acc, (acc[i] ?? 0) + (c.to - c.from)], [0]);
const s6 = starts(S6_CLIPS), s7 = starts(S7_CLIPS);

/** Shots in order, their lengths in seconds, and the narration line that starts at each cue. */
export const SHOTS: { id: string; seconds: number; cues: { line: string; at: number }[] }[] = [
  { id: "S1", seconds: 17.5, cues: [] },
  { id: "S2", seconds: 17.5, cues: [{ line: "s2a", at: 0.5 }, { line: "s2b", at: 10.7 }] },
  { id: "S3", seconds: 13.5, cues: [{ line: "s3a", at: 1.2 }, { line: "s3b", at: 7.4 }] },
  { id: "S4", seconds: S4_SECONDS, cues: [
    { line: "s4a", at: 0.6 }, { line: "s4b", at: S4.answered + 0.6 }, { line: "s4c", at: S4.page + 0.5 }, { line: "s4d", at: S4.video + 0.4 },
    { line: "s4e", at: S4.cut + S4.footage + 1.1 }] },
  { id: "S5", seconds: 31, cues: [{ line: "s5a", at: 0.5 }, { line: "s5b", at: 9.2 }, { line: "s5c", at: 21.0 }] },
  { id: "S6", seconds: span(S6_CLIPS), cues: [{ line: "s6a", at: 0.5 }, { line: "s6b", at: s6[2] + 0.2 }, { line: "s6c", at: s6[4] + 0.5 }] },
  { id: "S7", seconds: span(S7_CLIPS), cues: [
    { line: "s7a", at: 0.3 }, { line: "s7b", at: S7_WRONG + 1.9 }, { line: "s7c", at: s7[1] + 0.6 }, { line: "s7d", at: s7[2] + 0.5 }, { line: "s7e", at: s7[3] + 0.4 }] },
  { id: "S7b", seconds: span(S7B.clips) + S7B.movieSeconds + 0.3, cues: [{ line: "s7f", at: 0.3 }] },
  { id: "S8", seconds: S8.seconds, cues: S8.cues },
  { id: "S9", seconds: 15.5, cues: [{ line: "s9a", at: 1.5 }] },
];

export const frames = (seconds: number) => Math.round(seconds * FPS);
export const SHOT_START = SHOTS.reduce<Record<string, number>>((acc, shot, i) => ({ ...acc, [shot.id]: i === 0 ? 0 : acc[SHOTS[i - 1].id] + frames(SHOTS[i - 1].seconds) }), {});
export const TOTAL_FRAMES = SHOTS.reduce((t, shot) => t + frames(shot.seconds), 0);
