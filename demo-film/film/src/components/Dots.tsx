import React from "react";
import { interpolateColors, useCurrentFrame } from "remotion";
import { color, ramp } from "../theme";

/**
 * The knowledge base, one dot per citable piece, in course order (textbook, slides, lectures).
 * `marks` holds a letter per piece: t = the file's own text, v = read by vision, s = speech.
 * The dots arrive plain, then each kind takes its colour when the narration reaches it.
 */
export const SPEECH = "#8aa0ff";
const PLAIN = "#5d5a53";
const TEXT = "#b9b4a9";

export const Dots: React.FC<{ marks: string; size: number; at: number; visionAt: number; speechAt: number }> = ({ marks, size, at, visionAt, speechAt }) => {
  const frame = useCurrentFrame();
  const columns = Math.ceil(Math.sqrt(marks.length));
  const pitch = size / columns;
  return (
    <svg width={size} height={Math.ceil(marks.length / columns) * pitch} style={{ overflow: "visible" }}>
      {marks.split("").map((mark, index) => {
        const order = index / marks.length;
        const shown = ramp(frame, at + order * 44, at + order * 44 + 8);
        if (shown <= 0) return null;
        const lit = mark === "v" ? ramp(frame, visionAt + order * 26, visionAt + order * 26 + 10) : mark === "s" ? ramp(frame, speechAt + order * 10, speechAt + order * 10 + 10) : ramp(frame, at + 50, at + 70);
        const target = mark === "v" ? color.cite : mark === "s" ? SPEECH : TEXT;
        return (
          <circle key={index} cx={(index % columns) * pitch + pitch / 2} cy={Math.floor(index / columns) * pitch + pitch / 2} r={pitch * (0.3 + 0.06 * lit)} opacity={shown}
            fill={interpolateColors(lit, [0, 1], [PLAIN, target])} />
        );
      })}
    </svg>
  );
};
