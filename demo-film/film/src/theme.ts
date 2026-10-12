// The film's visual grammar: a dark room, chalk-white type, and one accent. Orange always means
// "this came from a source" - the same rule the product follows.
import { Easing, interpolate } from "remotion";

export const FPS = 30;
export const W = 1920;
export const H = 1080;

export const color = {
  black: "#050505",
  ink: "#0c0b0a",
  chalk: "#f3efe6",
  dim: "#8f8a80",
  faint: "#4a4741",
  cite: "#f08a2a",
  citeSoft: "rgba(240,138,42,0.16)",
  paper: "#f5f2ea",
  outside: "#9a7fd1",
  good: "#4fb58a",
  bad: "#e0685c",
};

export const font = {
  serif: '"Iowan Old Style", "Charter", "Palatino", Georgia, serif',
  sans: '-apple-system, "SF Pro Display", "Helvetica Neue", Arial, sans-serif',
  mono: '"SF Mono", Menlo, Consolas, monospace',
  deva: '"Kohinoor Devanagari", "Devanagari Sangam MN", "Iowan Old Style", serif',
};

export const sec = (seconds: number) => Math.round(seconds * FPS);

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
export const ease = Easing.bezier(0.22, 0.61, 0.2, 1);
export const easeInOut = Easing.bezier(0.6, 0, 0.2, 1);

/** 0 -> 1 between two frames, eased. */
export const ramp = (frame: number, from: number, to: number, easing = ease) =>
  interpolate(frame, [from, to], [0, 1], { ...clamp, easing });

/** 1 while inside [from, to], with eased edges of `edge` frames. */
export const window = (frame: number, from: number, to: number, edge = 12) =>
  Math.min(ramp(frame, from, from + edge), 1 - ramp(frame, to - edge, to));

export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

export const clock = (seconds: number) => `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
