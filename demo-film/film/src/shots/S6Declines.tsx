import React from "react";
import { AbsoluteFill } from "remotion";
import { Lower } from "../components/Lower";
import { Clip, Cuts, cutsFrames } from "../components/Take";
import film from "../../public/data/film.json";
import { S6_CLIPS } from "../timing";

// What it will not do. Two real questions: one from another subject, one that sounds like
// this course but is not in it. The waits between asking and answering are cut.
const CAMS = [
  [{ at: 0, x: 1536, y: 864, zoom: 0.92 }, { at: 1.0, x: 1536, y: 864, zoom: 0.92 }, { at: 3.6, x: 1340, y: 1260, zoom: 1.26 }],
  [{ at: 0, x: 1340, y: 330, zoom: 1.34 }, { at: 3.1, x: 1340, y: 330, zoom: 1.46 }],
  [{ at: 0, x: 1340, y: 950, zoom: 1.12 }, { at: 3.0, x: 1340, y: 1000, zoom: 1.2 }],
  [{ at: 0, x: 1340, y: 470, zoom: 1.3 }, { at: 4.2, x: 1340, y: 470, zoom: 1.44 }],
];
const CLIPS: Clip[] = S6_CLIPS.map((clip, i) => ({ name: "refuse", ...clip, cams: CAMS[i] }));
export const S6_FRAMES = cutsFrames(CLIPS) + 6;
const first = (CLIPS[0].to - CLIPS[0].from);
const second = first + (CLIPS[1].to - CLIPS[1].from) + (CLIPS[2].to - CLIPS[2].from);
const refusal = (film.results as any).grounding?.refusal;

export const S6Declines: React.FC = () => (
  <AbsoluteFill>
    <Cuts clips={CLIPS} />
    <Lower from={first + 0.4} to={first + 3.0} label="ANOTHER SUBJECT" value="“Not in your course material.”" />
    <Lower
      from={second + 0.5}
      to={second + 4.2}
      label={refusal ? "MEASURED ON QUESTIONS THE COURSE DOES NOT COVER" : "PHYSICS, BUT NOT THIS COURSE"}
      value={refusal ? `${refusal.off_material_declined} of ${refusal.off_material_declined + refusal.off_material_answered} declined` : "It still says no."}
    />
  </AbsoluteFill>
);
