import React from "react";
import { useCurrentFrame } from "remotion";
import { color, ramp } from "../theme";

/**
 * Four corner brackets that close on a region: the product "reading" something. The box is
 * given in frame pixels. They start wide and settle, like a camera finding focus.
 */
export const Reticle: React.FC<{ box: [number, number, number, number]; at: number; stroke?: string; out?: number }> = ({ box, at, stroke = color.cite, out }) => {
  const frame = useCurrentFrame();
  const t = ramp(frame, at, at + 22);
  const gone = out === undefined ? 0 : ramp(frame, out, out + 10);
  const grow = (1 - t) * 46;
  const [x0, y0, x1, y1] = [box[0] - grow, box[1] - grow, box[2] + grow, box[3] + grow];
  const arm = 34;
  const corners = [
    `M${x0},${y0 + arm} L${x0},${y0} L${x0 + arm},${y0}`,
    `M${x1 - arm},${y0} L${x1},${y0} L${x1},${y0 + arm}`,
    `M${x1},${y1 - arm} L${x1},${y1} L${x1 - arm},${y1}`,
    `M${x0 + arm},${y1} L${x0},${y1} L${x0},${y1 - arm}`,
  ];
  return (
    <svg width="100%" height="100%" style={{ position: "absolute", inset: 0, opacity: t * (1 - gone) }}>
      {corners.map((d) => (
        <path key={d} d={d} fill="none" stroke={stroke} strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" style={{ filter: `drop-shadow(0 0 10px ${stroke})` }} />
      ))}
    </svg>
  );
};

/** The citation thread: a line of light drawn from a claim to its source. */
export const Thread: React.FC<{ from: [number, number]; to: [number, number]; at: number; length?: number; bend?: number; out?: number }> = ({ from, to, at, length = 26, bend = 0.3, out }) => {
  const frame = useCurrentFrame();
  const t = ramp(frame, at, at + length);
  const gone = out === undefined ? 0 : ramp(frame, out, out + 12);
  const [x0, y0] = from;
  const [x1, y1] = to;
  const mx = (x0 + x1) / 2 - (y1 - y0) * bend;
  const my = (y0 + y1) / 2 + (x1 - x0) * bend;
  const d = `M${x0},${y0} Q${mx},${my} ${x1},${y1}`;
  const total = Math.hypot(x1 - x0, y1 - y0) * 1.25;
  return (
    <svg width="100%" height="100%" style={{ position: "absolute", inset: 0, opacity: 1 - gone }}>
      <path d={d} fill="none" stroke={color.cite} strokeWidth={3} strokeLinecap="round" strokeDasharray={total} strokeDashoffset={total * (1 - t)} style={{ filter: `drop-shadow(0 0 8px ${color.cite})` }} />
      <circle cx={x0} cy={y0} r={6} fill={color.cite} opacity={Math.min(1, t * 4)} />
      <circle cx={x1} cy={y1} r={7 * ramp(frame, at + length - 4, at + length + 8)} fill={color.cite} />
    </svg>
  );
};
