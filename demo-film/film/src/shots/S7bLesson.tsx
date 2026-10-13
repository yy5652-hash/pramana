import React from "react";
import { AbsoluteFill, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame } from "remotion";
import { Lower } from "../components/Lower";
import { Clip, Cuts, cutsFrames } from "../components/Take";
import film from "../../public/data/film.json";
import { S7B } from "../timing";
import { clock, color, ramp, sec } from "../theme";

// The product makes films too. A real take: the student asks for the lesson the learner model
// recommends, and the app cuts it. Then the lesson itself, exactly as it came out, from the
// scene in which the lecturer speaks. The time it took is measured in the take.
const CAMS = [
  [{ at: 0, x: 1536, y: 864, zoom: 0.92 }, { at: 1.1, x: 1536, y: 864, zoom: 0.92 }, { at: 2.7, x: 1744, y: 700, zoom: 1.12 }, { at: 5.0, x: 1744, y: 780, zoom: 1.16 }],
  [{ at: 0, x: 1744, y: 640, zoom: 1.05 }, { at: 4.8, x: 1744, y: 720, zoom: 1.12 }],
];
const CLIPS: Clip[] = S7B.clips.map((clip, i) => ({ ...clip, cams: CAMS[i] }));
const TAKE = cutsFrames(CLIPS);
const MOVIE = sec(S7B.movieSeconds);
export const S7B_FRAMES = TAKE + MOVIE + sec(0.3);
const first = S7B.clips[0].to - S7B.clips[0].from;
// Measured on every concept of the course, not on this one lesson (evaluation/results/lessons.json).
const measured = (film.results as any).lessons;
const cutIn = `CUT ON THIS LAPTOP IN ${clock(S7B.made).replace(/^0/, "")}`;
const WINDOW = { width: 1632, height: 918 };

export const S7bLesson: React.FC = () => {
  const frame = useCurrentFrame();
  const local = frame - TAKE;
  return (
    <AbsoluteFill style={{ background: color.black }}>
      <Sequence durationInFrames={TAKE + 4}>
        <Cuts clips={CLIPS} />
      </Sequence>
      <Sequence from={TAKE}>
        <AbsoluteFill style={{ opacity: ramp(local, 0, 9) }}>
          <div style={{ position: "absolute", left: (1920 - WINDOW.width) / 2, top: 96, ...WINDOW, borderRadius: 20, overflow: "hidden", boxShadow: "0 0 0 1px rgba(255,255,255,.12), 0 40px 120px rgba(0,0,0,.8)",
            transform: `scale(${0.985 + 0.015 * ramp(local, 0, 30)})` }}>
            <OffthreadVideo src={staticFile("lessons/demo.mp4")} startFrom={Math.round(S7B.movieFrom * 30)} style={{ width: "100%", height: "100%" }}
              volume={(f) => interpolate(f, [0, 8, MOVIE - 12, MOVIE], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })} />
          </div>
        </AbsoluteFill>
      </Sequence>
      <Lower from={0.5} to={first - 0.2} label="YOUR NEXT LESSON" value={S7B.concept} />
      {measured?.narration_support?.lines_judged ? (
        <Lower from={first + 0.5} to={TAKE / 30 - 0.2} label={`${cutIn} · EVERY SCENE IS A SOURCE`}
          value={`${Math.round(measured.narration_support.fully_supported * 100)}% of narrated lines supported, across all ${measured.lessons_made} concepts`} />
      ) : (
        <Lower from={first + 0.5} to={TAKE / 30 - 0.2} label={cutIn} value="every scene is a source" />
      )}
      <Lower top right from={TAKE / 30 + 0.7} to={(TAKE + MOVIE) / 30} label={`THE LESSON ITSELF · ${clock(S7B.lessonSeconds).replace(/^0/, "")}`} value={S7B.lecturer ? "your lecturer's own voice" : "your own textbook"} />
    </AbsoluteFill>
  );
};
