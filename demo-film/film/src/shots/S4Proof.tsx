import React from "react";
import { AbsoluteFill, Sequence, interpolate, useCurrentFrame } from "remotion";
import { Footage } from "../components/Footage";
import { Reticle } from "../components/Reticle";
import { Take } from "../components/Take";
import { Tex } from "../components/Tex";
import { Tag, Words } from "../components/Type";
import { S4, S4_SECONDS } from "../timing";
import { clock, color, font, ramp, sec } from "../theme";

// The film's centre: a real question to the real app, and the numbers in its answer opening
// the textbook page and the second of the lecture. Then the cut the product makes possible:
// from the small player in the app to the lecture itself, at the same instant.
const { trim: TRIM, cut: CUT, passageStart, footage: FOOTAGE_SECONDS } = S4;
const at = (key: "typed" | "asked" | "answered" | "page" | "video" | "play") => S4[key];
const SOURCE_AT_CUT = passageStart + 4.2;
export const S4_FRAMES = sec(S4_SECONDS);
const BOARD_BOX: [number, number, number, number] = [1020, 262, 1420, 452];

const Beat: React.FC<{ from: number; to: number; label: string; value: string }> = ({ from, to, label, value }) => {
  const frame = useCurrentFrame();
  const t = Math.min(ramp(frame, sec(from), sec(from) + 14), 1 - ramp(frame, sec(to) - 12, sec(to)));
  return (
    <div style={{ position: "absolute", left: 84, bottom: 76, opacity: t, transform: `translateY(${(1 - t) * 14}px)`, padding: "18px 28px 20px", borderRadius: 16, background: "rgba(6,6,6,.94)", backdropFilter: "blur(16px)", boxShadow: "0 12px 50px rgba(0,0,0,.5)" }}>
      <div style={{ fontFamily: font.mono, fontSize: 26, color: color.dim, letterSpacing: "0.08em" }}>{label}</div>
      <div style={{ fontFamily: font.mono, fontSize: 60, color: color.cite, marginTop: 4 }}>{value}</div>
    </div>
  );
};

export const S4Proof: React.FC = () => {
  const frame = useCurrentFrame();
  const cut = sec(CUT);
  const local = frame - cut;
  const freeze = sec(FOOTAGE_SECONDS);
  const held = ramp(local, freeze, freeze + 24);
  return (
    <AbsoluteFill style={{ background: color.black }}>
      <Sequence durationInFrames={cut + 2}>
        <Take
          name="ask"
          from={TRIM}
          cams={[
            { at: 0, x: 1536, y: 864, zoom: 0.9 },
            { at: 0.9, x: 1536, y: 864, zoom: 0.9 },
            { at: at("typed") - 1.4, x: 1330, y: 1250, zoom: 1.28 },
            { at: at("asked") + 0.2, x: 1330, y: 1250, zoom: 1.28 },
            { at: at("answered") + 0.5, x: 1130, y: 600, zoom: 1.42 },
            { at: at("page") - 0.5, x: 1130, y: 600, zoom: 1.42 },
            { at: at("page") + 0.9, x: 1975, y: 770, zoom: 1.4 },
            { at: at("video") - 0.3, x: 1975, y: 770, zoom: 1.4 },
            { at: at("video") + 1.0, x: 2040, y: 620, zoom: 1.5 },
            { at: CUT - 0.7, x: 2380, y: 574, zoom: 1.58 },
            { at: CUT, x: 2420, y: 574, zoom: 2.3 },
          ]}
        />
        <Beat from={at("answered") + 0.6} to={at("page") - 0.2} label="EVERY SENTENCE" value="carries a number" />
        <Beat from={at("page") + 0.8} to={at("video") - 0.2} label="TEXTBOOK" value="p. 223" />
        <Beat from={at("video") + 0.9} to={CUT - 0.1} label="LECTURE 4.1" value="02:58" />
      </Sequence>

      {/* the lecture itself, continuing from the same instant */}
      <Sequence from={cut} durationInFrames={S4_FRAMES - cut}>
        <AbsoluteFill style={{ opacity: ramp(local, 0, 8) }}>
          <Footage
            file="MIT8_01F16_L04v01_360p.mp4"
            from={SOURCE_AT_CUT}
            volume={(f) => interpolate(f, [0, 10, freeze - 14, freeze + 8], [0, 1.7, 1.7, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}
            freezeAt={freeze}
            style={{ opacity: 1 - held * 0.6 }}
          />
          <div style={{ position: "absolute", right: 96, bottom: 84, textAlign: "right" }}>
            <div style={{ fontFamily: font.mono, fontSize: 30, color: color.dim, letterSpacing: "0.06em" }}>MIT 8.01 · LECTURE 4.1 · CITED AT 02:58</div>
            <div style={{ fontFamily: font.mono, fontSize: 58, color: color.cite, marginTop: 6 }}>{clock(SOURCE_AT_CUT + Math.min(Math.max(local, 0), freeze) / 30)}</div>
          </div>
          <Reticle box={BOARD_BOX} at={freeze + 6} />
          <div style={{ position: "absolute", left: 104, top: 280, width: 640 }}>
            <Tag at={freeze + 26} size={26}>THE ANSWER</Tag>
            <div style={{ opacity: ramp(local, freeze + 30, freeze + 52), transform: `translateY(${(1 - ramp(local, freeze + 30, freeze + 52)) * 14}px)` }}>
              <Tex size={104} color={color.chalk} style={{ marginTop: 22, textAlign: "left" }}>{"\\vec{F}_{net} = \\frac{d\\vec{p}}{dt}"}</Tex>
            </div>
            <div style={{ marginTop: 34 }}>
              <Words text="and its proof." at={freeze + 66} size={66} accent={["proof"]} />
            </div>
          </div>
        </AbsoluteFill>
      </Sequence>
    </AbsoluteFill>
  );
};
