import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Tag, Words } from "../components/Type";
import { color, font, ramp, sec } from "../theme";

// The name. One subject, one arc, a full second of stillness on the wordmark.
export const S3_FRAMES = sec(13.5);
const WORD = "प्रमाण";

export const S3Reveal: React.FC = () => {
  const frame = useCurrentFrame();
  const glyphs = ramp(frame, 0, 44);
  const settle = ramp(frame, 150, 190);       // the Devanagari gives way to the wordmark
  const mark = ramp(frame, 176, 214);
  return (
    <AbsoluteFill style={{ background: color.black, alignItems: "center", justifyContent: "center" }}>
      {/* a line of light under the word, the film's thread at rest */}
      <div style={{ position: "absolute", top: 660, left: 960 - 330 * ramp(frame, 26, 84), width: 660 * ramp(frame, 26, 84), height: 3, background: color.cite, boxShadow: `0 0 18px ${color.cite}`, opacity: 1 - settle }} />
      <div style={{ position: "absolute", top: 362, width: "100%", textAlign: "center", opacity: (1 - settle), transform: `scale(${1 + settle * 0.05})` }}>
        <div style={{ fontFamily: font.deva, fontSize: 250, color: color.chalk, lineHeight: 1.15, clipPath: `inset(0 ${(1 - glyphs) * 100}% 0 0)`, textShadow: "0 0 40px rgba(243,239,230,.25)" }}>{WORD}</div>
      </div>
      <div style={{ position: "absolute", top: 700, width: "100%", display: "flex", justifyContent: "center", gap: 34, opacity: 1 - settle }}>
        <Tag at={70} size={38} fill={color.chalk}>pramāṇa</Tag>
        <Tag at={82} size={38} fill={color.dim}>Sanskrit</Tag>
        <Tag at={94} size={38} fill={color.cite}>proof · the means by which we know</Tag>
      </div>
      <div style={{ position: "absolute", top: 380, width: "100%", textAlign: "center", opacity: mark, transform: `translateY(${(1 - mark) * 18}px)` }}>
        <div style={{ fontFamily: font.serif, fontSize: 190, fontWeight: 600, color: color.chalk, letterSpacing: "-0.02em" }}>Pramana</div>
      </div>
      <div style={{ position: "absolute", top: 640, left: 110, width: 1700, textAlign: "center" }}>
        <Words text="A study companion that can only say what your course says" at={222} size={52} fill={color.dim} stagger={2} style={{ textAlign: "center" }} />
        <Words text="and shows you exactly where." at={262} size={52} fill={color.chalk} accent={["exactly", "where"]} stagger={3} style={{ textAlign: "center", marginTop: 10 }} />
      </div>
    </AbsoluteFill>
  );
};
