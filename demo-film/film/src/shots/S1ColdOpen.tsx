import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Footage } from "../components/Footage";
import { Reticle, Thread } from "../components/Reticle";
import { Tex } from "../components/Tex";
import { Tag } from "../components/Type";
import { clock, color, font, ramp, sec } from "../theme";

// Source: MIT 8.01SC lecture 4.1. The lecturer writes F = ma between 1:57 and 2:05.
export const SOURCE_START = 115.2;
export const FREEZE = sec(11.3);            // sequence frame: the equation is complete
export const S1_FRAMES = sec(17.5);
// Where the handwriting sits in the 1920x1080 frame (measured on the frozen frame).
export const BOARD_BOX: [number, number, number, number] = [1082, 118, 1392, 232];

export const S1ColdOpen: React.FC = () => {
  const frame = useCurrentFrame();
  const fadeIn = ramp(frame, 0, 36);
  const held = ramp(frame, FREEZE, FREEZE + 26);
  const sourceTime = SOURCE_START + Math.min(frame, FREEZE) / 30;
  return (
    <AbsoluteFill style={{ background: color.black }}>
      <Footage
        file="MIT8_01F16_L04v01_360p.mp4"
        from={SOURCE_START}
        volume={(f) => interpolate(f, [0, 30, FREEZE - 20, FREEZE + 6], [0, 1.7, 1.7, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}
        freezeAt={FREEZE}
        style={{ opacity: fadeIn * (1 - held * 0.62) }}
      />
      {/* the source and its running timecode */}
      <div style={{ position: "absolute", left: 96, bottom: 84, opacity: fadeIn * (1 - held * 0.2) }}>
        <div style={{ fontFamily: font.mono, fontSize: 30, color: color.dim, letterSpacing: "0.06em" }}>MIT 8.01 · LECTURE 4.1</div>
        <div style={{ fontFamily: font.mono, fontSize: 58, color: frame >= FREEZE ? color.cite : color.chalk, marginTop: 6 }}>{clock(sourceTime)}</div>
      </div>
      {/* what this film is about, said quietly while the lecture runs */}
      <div style={{ position: "absolute", left: 96, top: 84, opacity: Math.min(ramp(frame, sec(3.6), sec(4.6)), 1 - ramp(frame, sec(9.6), sec(10.6))) }}>
        <div style={{ fontFamily: font.mono, fontSize: 26, color: color.cite, letterSpacing: "0.14em" }}>PRAMANA</div>
        <div style={{ fontFamily: font.serif, fontSize: 40, color: color.chalk, marginTop: 8, lineHeight: 1.25 }}>A tutor that can only say<br />what your course says.</div>
      </div>
      {/* the product reads the board */}
      <Reticle box={BOARD_BOX} at={FREEZE + 10} />
      <Thread from={[BOARD_BOX[0] - 14, (BOARD_BOX[1] + BOARD_BOX[3]) / 2 + 30]} to={[548, 372]} at={FREEZE + 38} bend={-0.2} />
      <div style={{ position: "absolute", left: 104, top: 318, width: 540 }}>
        <Tag at={FREEZE + 56} size={26}>READ FROM THE GLASS · BY A VISION MODEL</Tag>
        <div style={{ opacity: ramp(frame, FREEZE + 62, FREEZE + 84), transform: `translateY(${(1 - ramp(frame, FREEZE + 62, FREEZE + 84)) * 14}px)` }}>
          <Tex size={108} color={color.chalk} style={{ marginTop: 26, textAlign: "left" }}>{"\\vec{F} = m\\vec{a}"}</Tex>
        </div>
      </div>
    </AbsoluteFill>
  );
};
