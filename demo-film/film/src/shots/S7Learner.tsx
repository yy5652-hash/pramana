import React from "react";
import { AbsoluteFill } from "remotion";
import { Lower } from "../components/Lower";
import { Clip, Cuts, cutsFrames } from "../components/Take";
import film from "../../public/data/film.json";
import { S7_CLIPS, S7_FOCUS, S7_SHIFT, S7_WRONG } from "../timing";

// The other half of the product: it writes checked questions, reads a wrong answer as a
// misconception, and keeps a model of what the student knows. Three real takes.
// Aim at a rectangle of the take: its centre, at the zoom that lets it fill `share` of the frame.
const TAKE = { w: 3072, h: 1728 };
const aim = (rect: number[] | undefined, fallback: { x: number; y: number; zoom: number }, share = 0.6, most = 1.5) => {
  if (!rect) return fallback;
  const [x0, y0, x1, y1] = rect;
  const zoom = Math.max(1.05, Math.min(most, (share * TAKE.w) / Math.max(x1 - x0, 1), (0.74 * TAKE.h) / Math.max(y1 - y0, 1)));
  return { x: (x0 + x1) / 2, y: (y0 + y1) / 2, zoom };
};
const question = aim(S7_FOCUS.question && S7_FOCUS.verdict ? [S7_FOCUS.question[0], S7_FOCUS.question[1], S7_FOCUS.question[2], Math.min(S7_FOCUS.verdict[1] + 120, S7_FOCUS.question[1] + 700)] : undefined, { x: 1120, y: 560, zoom: 1.22 }, 0.66, 1.3);
const verdict = aim(S7_FOCUS.verdict, { x: 1120, y: 900, zoom: 1.34 }, 0.62, 1.4);
const source = aim(S7_FOCUS.source, { x: 2000, y: 860, zoom: 1.3 }, 0.52, 1.45);
const meter = aim(S7_FOCUS.meter, verdict, 0.3, 1.6);
const CAMS = [
  // a question, a wrong answer, and what follows from it, in order: the learner model moves
  // (the meter), the answer is read (the verdict), and the page it should have come from
  [{ at: 0, ...question }, { at: 4.2, ...question }, { at: 5.1, ...meter }, { at: 6.7, ...meter }, { at: 7.7, ...verdict }, { at: 9.5, ...verdict }, { at: 10.7, ...source }],
  // the course map, coloured by this student's mastery
  [{ at: 0, x: 1536, y: 864, zoom: 0.96 }, { at: 1.2, x: 1536, y: 864, zoom: 0.96 }, { at: 3.4, x: 1700, y: 900, zoom: 1.2 }, { at: 9, x: 1700, y: 980, zoom: 1.26 }],
  // every number explains itself
  [{ at: 0, x: 1536, y: 864, zoom: 0.96 }, { at: 0.9, x: 1536, y: 864, zoom: 0.96 }, { at: 2.8, x: 2180, y: 900, zoom: 1.4 }, { at: 6.2, x: 2180, y: 1000, zoom: 1.4 }],
  // and the week ahead, planned from the forgetting curve
  [{ at: 0, x: 1700, y: 700, zoom: 1.1 }, { at: 5.6, x: 1700, y: 880, zoom: 1.2 }],
];
const CLIPS: Clip[] = S7_CLIPS.map((clip, i) => ({ ...clip, cams: CAMS[i] }));
export const S7_FRAMES = cutsFrames(CLIPS) + 6;
const length = (i: number) => CLIPS[i].to - CLIPS[i].from;
const t1 = length(0), t2 = t1 + length(1), t3 = t2 + length(2);
const stats = film.stats;
const verified = Object.values(stats.questions_verified as Record<string, number>).reduce((a, b) => a + b, 0);
const rejected = Object.values(stats.questions_rejected as Record<string, number>).reduce((a, b) => a + b, 0);

export const S7Learner: React.FC = () => (
  <AbsoluteFill>
    <Cuts clips={CLIPS} />
    <Lower from={0.5} to={4.4} label="QUESTIONS WRITTEN FROM THE COURSE" value={`${verified + rejected} drafted · ${rejected} rejected before use`} />
    {S7_SHIFT ? <Lower from={S7_WRONG + 0.6} to={S7_WRONG + 2.8} label="THE LEARNER MODEL MOVES WITH EVERY ANSWER" value={`mastery ${S7_SHIFT}`} /> : null}
    <Lower from={S7_WRONG + 3.2} to={t1 - 0.2} label="A WRONG ANSWER IS READ, NOT JUST MARKED" value="the misconception, and the page" right />
    <Lower from={t1 + 0.6} to={t2 - 0.3} label={`${stats.concepts} CONCEPTS · ${stats.prerequisite_edges} PREREQUISITE LINKS`} value="what you know, and what it rests on" />
    <Lower from={t2 + 0.6} to={t3 - 0.3} label="THE LEARNER MODEL" value="every number explains itself" />
    <Lower from={t3 + 0.5} to={t3 + length(3) - 0.2} label="PLANNED FROM THE FORGETTING CURVE" value="what to study, and when" />
  </AbsoluteFill>
);
