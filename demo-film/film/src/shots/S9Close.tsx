import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Footage } from "../components/Footage";
import { Tag, Words } from "../components/Type";
import { color, font, ramp, sec } from "../theme";

// Back to the glass. The lecturer derives the work-energy theorem; the film ends on its line.
export const S9_FRAMES = sec(15.5);
const CREDITS = sec(8.6);

export const S9Close: React.FC = () => {
  const frame = useCurrentFrame();
  const out = ramp(frame, CREDITS - 16, CREDITS + 4);
  return (
    <AbsoluteFill style={{ background: color.black }}>
      <Footage
        file="MIT8_01F16_L20v05_360p.mp4"
        from={93.5}
        volume={(f) => interpolate(f, [0, 16, sec(3.2), sec(4.4)], [0, 0.9, 0.9, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}
        style={{ opacity: ramp(frame, 0, 20) * (0.62 - 0.3 * ramp(frame, sec(1.2), sec(2.4)) - 0.32 * out) }}
      />
      <div style={{ position: "absolute", left: 0, right: 0, top: 388, textAlign: "center", opacity: 1 - out }}>
        <Words text="Every answer shows its proof." at={sec(1.6)} size={104} accent={["proof"]} stagger={4} style={{ textAlign: "center" }} />
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 300, textAlign: "center", opacity: ramp(frame, CREDITS + 4, CREDITS + 26) }}>
        <div style={{ fontFamily: font.deva, fontSize: 70, color: color.cite }}>प्रमाण</div>
        <div style={{ fontFamily: font.serif, fontSize: 150, fontWeight: 600, color: color.chalk, letterSpacing: "-0.02em", lineHeight: 1.1 }}>Pramana</div>
        <Tag at={CREDITS + 30} size={36} fill={color.chalk} style={{ marginTop: 26 }}>github.com/yy5652-hash/pramana</Tag>
      </div>
      <div style={{ position: "absolute", left: 120, right: 120, bottom: 70, textAlign: "center", fontFamily: font.mono, fontSize: 22, lineHeight: 1.6, color: color.dim, opacity: ramp(frame, CREDITS + 44, CREDITS + 60) }}>
        Lecture footage: MIT OpenCourseWare, 8.01SC Classical Mechanics · Textbook: OpenStax, University Physics Vol. 1 (both CC BY-NC-SA 4.0) · Slides: Collin College PHYS 2425 (CC BY 4.0)
        <br />
        Multimodal AI Hackathon 2026 · Track D · This film is released under CC BY-NC-SA 4.0
      </div>
    </AbsoluteFill>
  );
};
