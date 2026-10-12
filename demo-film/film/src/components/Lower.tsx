import React from "react";
import { useCurrentFrame } from "remotion";
import { color, font, ramp, sec } from "../theme";

/** A caption card over a take: a small label and one large value, in, held, out. Bottom left unless told otherwise. */
export const Lower: React.FC<{ from: number; to: number; label: string; value: string; tone?: string; right?: boolean; top?: boolean }> = ({ from, to, label, value, tone = color.cite, right = false, top = false }) => {
  const frame = useCurrentFrame();
  const t = Math.min(ramp(frame, sec(from), sec(from) + 14), 1 - ramp(frame, sec(to) - 12, sec(to)));
  if (t <= 0) return null;
  return (
    <div style={{ position: "absolute", [right ? "right" : "left"]: 84, [top ? "top" : "bottom"]: top ? 64 : 76, opacity: t, transform: `translateY(${(1 - t) * 14}px)`, padding: "18px 28px 20px", borderRadius: 16, background: "rgba(6,6,6,.94)", backdropFilter: "blur(16px)", boxShadow: "0 12px 50px rgba(0,0,0,.5)", maxWidth: 1100 }}>
      <div style={{ fontFamily: font.mono, fontSize: 26, color: color.dim, letterSpacing: "0.08em" }}>{label}</div>
      <div style={{ fontFamily: font.serif, fontSize: 54, color: tone, marginTop: 4, lineHeight: 1.15 }}>{value}</div>
    </div>
  );
};
