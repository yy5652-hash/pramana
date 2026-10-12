import React from "react";
import { useCurrentFrame } from "remotion";
import { color, ease, font, ramp } from "../theme";

/** Words that rise into place one after another. `at` is the frame the first word starts. */
export const Words: React.FC<{
  text: string;
  at?: number;
  stagger?: number;
  size?: number;
  family?: string;
  weight?: number;
  fill?: string;
  out?: number;            // frame at which the line fades out (optional)
  accent?: string[];       // words drawn in the citation colour
  style?: React.CSSProperties;
}> = ({ text, at = 0, stagger = 3, size = 72, family = font.serif, weight = 500, fill = color.chalk, out, accent = [], style }) => {
  const frame = useCurrentFrame();
  const fade = out === undefined ? 1 : 1 - ramp(frame, out, out + 12);
  return (
    <div style={{ fontFamily: family, fontSize: size, fontWeight: weight, color: fill, lineHeight: 1.18, letterSpacing: "-0.012em", opacity: fade, ...style }}>
      {text.split(" ").map((word, index) => {
        const t = ramp(frame, at + index * stagger, at + index * stagger + 16, ease);
        const bare = word.replace(/[.,;:!?—]/g, "");
        return (
          <span key={index} style={{ display: "inline-block", whiteSpace: "pre", opacity: t, transform: `translateY(${(1 - t) * 0.32}em)`, filter: `blur(${(1 - t) * 6}px)`, color: accent.includes(bare) ? color.cite : undefined }}>
            {word + " "}
          </span>
        );
      })}
    </div>
  );
};

/** A small mono label: locators, timecodes, credits. */
export const Tag: React.FC<{ children: React.ReactNode; at?: number; size?: number; fill?: string; style?: React.CSSProperties }> = ({ children, at = 0, size = 30, fill = color.cite, style }) => {
  const frame = useCurrentFrame();
  const t = ramp(frame, at, at + 14);
  return (
    <div style={{ fontFamily: font.mono, fontSize: size, color: fill, letterSpacing: "0.04em", opacity: t, transform: `translateY(${(1 - t) * 8}px)`, ...style }}>{children}</div>
  );
};
