import React from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";
import voice from "./generated/voice.json";
import { S1ColdOpen } from "./shots/S1ColdOpen";
import { S2ThreeTimes } from "./shots/S2ThreeTimes";
import { S3Reveal } from "./shots/S3Reveal";
import { S4Proof } from "./shots/S4Proof";
import { S5Vision } from "./shots/S5Vision";
import { S6Declines } from "./shots/S6Declines";
import { S7Learner } from "./shots/S7Learner";
import { S7bLesson } from "./shots/S7bLesson";
import { S8Evidence } from "./shots/S8Evidence";
import { S9Close } from "./shots/S9Close";
import { color } from "./theme";
import { FPS, SHOTS, SHOT_START, frames } from "./timing";

const COMPONENT: Record<string, React.FC> = {
  S1: S1ColdOpen, S2: S2ThreeTimes, S3: S3Reveal, S4: S4Proof, S5: S5Vision, S6: S6Declines, S7: S7Learner, S7b: S7bLesson, S8: S8Evidence, S9: S9Close,
};

const EDGE = 5;   // frames each shot takes to come up from black and to go back down

/** A shot between two breaths of black, so the dark stage and the lit page never collide in a hard cut. */
const Breath: React.FC<{ length: number; first: boolean; last: boolean; children: React.ReactNode }> = ({ length, first, last, children }) => {
  const frame = useCurrentFrame();
  const up = first ? 1 : interpolate(frame, [0, EDGE], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const down = last ? 1 : interpolate(frame, [length - EDGE, length], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <AbsoluteFill style={{ opacity: Math.min(up, down) }}>{children}</AbsoluteFill>;
};

/** Fine grain and a soft vignette over everything: the footage, the type and the takes share one surface. */
const Surface: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <svg width="100%" height="100%" style={{ opacity: 0.07, mixBlendMode: "overlay" }}>
        <filter id="grain">
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed={frame % 12} />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width="100%" height="100%" filter="url(#grain)" />
      </svg>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at center, rgba(0,0,0,0) 62%, rgba(0,0,0,0.22) 100%)" }} />
    </AbsoluteFill>
  );
};

/** The film: nine shots end to end, the narration laid in at its cues, and the bed underneath. */
export const Film: React.FC<{ music?: boolean }> = ({ music = true }) => (
  <AbsoluteFill style={{ background: color.black }}>
    {SHOTS.map((shot, index) => {
      const Shot = COMPONENT[shot.id];
      const length = frames(shot.seconds);
      return (
        <Sequence key={shot.id} name={shot.id} from={SHOT_START[shot.id]} durationInFrames={length}>
          <Breath length={length} first={index === 0} last={index === SHOTS.length - 1}>
            <Shot />
          </Breath>
        </Sequence>
      );
    })}
    <Surface />
    {SHOTS.flatMap((shot) =>
      shot.cues.map((cue) => (
        <Sequence key={cue.line} name={cue.line} from={SHOT_START[shot.id] + frames(cue.at)} durationInFrames={Math.ceil(((voice as Record<string, number>)[cue.line] + 0.3) * FPS)}>
          <Audio src={staticFile(`voice/${cue.line}.wav`)} volume={1} />
        </Sequence>
      )),
    )}
    {music ? <Audio src={staticFile("audio/bed.wav")} volume={1} /> : null}
  </AbsoluteFill>
);
