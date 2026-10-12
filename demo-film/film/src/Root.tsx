import React from "react";
import { Composition } from "remotion";
import { Film } from "./Film";
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
import { H, W } from "./theme";
import { FPS, SHOTS, TOTAL_FRAMES, frames } from "./timing";

const COMPONENT: Record<string, React.FC> = {
  S1: S1ColdOpen, S2: S2ThreeTimes, S3: S3Reveal, S4: S4Proof, S5: S5Vision, S6: S6Declines, S7: S7Learner, S7b: S7bLesson, S8: S8Evidence, S9: S9Close,
};

export const Root: React.FC = () => (
  <>
    <Composition id="Film" component={Film} durationInFrames={TOTAL_FRAMES} fps={FPS} width={W} height={H} defaultProps={{ music: true }} />
    {SHOTS.map((shot) => (
      <Composition key={shot.id} id={shot.id} component={COMPONENT[shot.id]} durationInFrames={frames(shot.seconds)} fps={FPS} width={W} height={H} />
    ))}
  </>
);
