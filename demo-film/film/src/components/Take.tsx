import React from "react";
import { AbsoluteFill, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { easeInOut } from "../theme";

/** One camera position over a take: the point of the take (in take pixels) held at frame centre, and a zoom. */
export type Cam = { at: number; x: number; y: number; zoom: number };   // `at` in seconds from the start of this sequence

const TAKE_W = 3072, TAKE_H = 1728;

/**
 * A real recording of the app, shown as a lit window in the film's dark room. Takes are
 * captured at 3072x1728, so the camera can push in to 1.6x and stay pixel-sharp.
 * zoom = 1 fits the take to the frame; below 1 it floats with a margin and rounded corners.
 */
export const Take: React.FC<{ name: string; from: number; cams: Cam[]; volume?: number }> = ({ name, from, cams, volume = 0 }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const t = frame / fps;
  const times = cams.map((c) => c.at);
  const at = (key: "x" | "y" | "zoom") => (cams.length === 1 ? cams[0][key] : interpolate(t, times, cams.map((c) => c[key]), { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: easeInOut }));
  const zoom = at("zoom");
  const k = (width / TAKE_W) * zoom;
  // Once the take fills the frame, the camera may not look past its edges.
  const halfW = width / 2 / k, halfH = height / 2 / k;
  const within = (value: number, half: number, size: number) => (zoom >= 1 ? Math.min(Math.max(value, half), size - half) : value);
  const left = width / 2 - within(at("x"), halfW, TAKE_W) * k;
  const top = height / 2 - within(at("y"), halfH, TAKE_H) * k;
  const floating = Math.max(0, Math.min(1, (1 - zoom) / 0.1));       // 1 when the whole window is in view
  return (
    <AbsoluteFill style={{ background: "#050505" }}>
      <div style={{ position: "absolute", left, top, width: TAKE_W * k, height: TAKE_H * k, borderRadius: 22 * floating, overflow: "hidden",
        boxShadow: `0 0 0 1px rgba(255,255,255,${0.1 * floating}), 0 40px 120px rgba(0,0,0,${0.75 * floating})` }}>
        <OffthreadVideo src={staticFile(`takes/${name}.mp4`)} startFrom={Math.round(from * fps)} volume={volume} muted={volume === 0} style={{ width: "100%", height: "100%" }} />
      </div>
    </AbsoluteFill>
  );
};

/** One piece of a take: play it from `from` to `to` (seconds of the take) under its own camera. */
export type Clip = { name: string; from: number; to: number; cams: Cam[] };

const OVERLAP = 7;

/** Clips of real takes played back to back. Waiting time between them is cut, never sped up. */
export const Cuts: React.FC<{ clips: Clip[]; children?: (clipIndex: number, clipFrame: number) => React.ReactNode }> = ({ clips, children }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  let start = 0;
  const placed = clips.map((clip) => {
    const length = Math.round((clip.to - clip.from) * fps);
    const item = { clip, start, length };
    start += length;
    return item;
  });
  const active = placed.findIndex((p) => frame >= p.start && frame < p.start + p.length);
  return (
    <AbsoluteFill style={{ background: "#050505" }}>
      {placed.map(({ clip, start: begin, length }, index) => (
        // Each piece runs a few frames into the next one, which fades in over it: a dissolve, never a dip to black.
        <Sequence key={index} from={begin} durationInFrames={length + (index < placed.length - 1 ? OVERLAP : 0)} layout="none">
          <AbsoluteFill style={{ opacity: index === 0 ? 1 : interpolate(frame - begin, [0, OVERLAP], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>
            <Take name={clip.name} from={clip.from} cams={clip.cams} />
          </AbsoluteFill>
        </Sequence>
      ))}
      {children && active >= 0 ? children(active, frame - placed[active].start) : null}
    </AbsoluteFill>
  );
};

export const cutsFrames = (clips: Clip[], fps = 30) => clips.reduce((total, clip) => total + Math.round((clip.to - clip.from) * fps), 0);
