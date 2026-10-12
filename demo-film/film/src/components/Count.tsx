import React from "react";
import { useCurrentFrame } from "remotion";
import { color, ease, font, ramp } from "../theme";

/** A number that counts up to its measured value and then holds. */
export const Count: React.FC<{ value: number; at: number; frames?: number; suffix?: string; decimals?: number; label: string; note?: string; fill?: string; size?: number }> = ({ value, at, frames = 34, suffix = "", decimals = 0, label, note, fill = color.chalk, size = 150 }) => {
  const frame = useCurrentFrame();
  const t = ramp(frame, at, at + frames, ease);
  const shown = (value * t).toFixed(decimals);
  const appear = ramp(frame, at - 6, at + 10);
  return (
    <div style={{ opacity: appear, transform: `translateY(${(1 - appear) * 18}px)` }}>
      <div style={{ fontFamily: font.serif, fontSize: size, fontWeight: 600, color: fill, lineHeight: 1, letterSpacing: "-0.02em", fontVariantNumeric: "tabular-nums" }}>
        {Number(shown).toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}
        <span style={{ fontSize: size * 0.5 }}>{suffix}</span>
      </div>
      <div style={{ fontFamily: font.sans, fontSize: 38, color: color.chalk, marginTop: 14 }}>{label}</div>
      {note ? <div style={{ fontFamily: font.mono, fontSize: 24, color: color.dim, marginTop: 8, letterSpacing: "0.03em" }}>{note}</div> : null}
    </div>
  );
};
