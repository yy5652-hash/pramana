import React from "react";
import { AbsoluteFill, Img, staticFile, useCurrentFrame } from "remotion";
import { Crop } from "../components/Crop";
import { Footage } from "../components/Footage";
import { Tag, Words } from "../components/Type";
import { color, font, lerp, ramp, sec } from "../theme";

// One idea, stated three times in three media. Then the chatbot that knows none of them.
export const S2_FRAMES = sec(17.5);
const PANEL_W = 540, PANEL_H = 420, GAP = 54, TOP = 372;
const LEFT = (1920 - 3 * PANEL_W - 2 * GAP) / 2;
const CHAT = sec(10.2);    // the chatbot beat begins

const Panel: React.FC<{ index: number; label: string; where: string; children: React.ReactNode }> = ({ index, label, where, children }) => {
  const frame = useCurrentFrame();
  const at = 34 + index * 26;
  const t = ramp(frame, at, at + 24);
  const away = ramp(frame, CHAT - 8, CHAT + 18);
  return (
    <div style={{ position: "absolute", left: LEFT + index * (PANEL_W + GAP), top: TOP + (1 - t) * 40, opacity: t * lerp(1, 0.16, away), filter: `blur(${away * 5}px)` }}>
      <div style={{ width: PANEL_W, height: PANEL_H, borderRadius: 14, overflow: "hidden", position: "relative", background: "#000", boxShadow: "0 0 0 1px rgba(255,255,255,.14), 0 30px 80px rgba(0,0,0,.6)" }}>{children}</div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginTop: 18, fontFamily: font.mono }}>
        <span style={{ fontSize: 26, color: color.dim, letterSpacing: "0.08em" }}>{label}</span>
        <span style={{ fontSize: 34, color: color.cite }}>{where}</span>
      </div>
    </div>
  );
};

export const S2ThreeTimes: React.FC = () => {
  const frame = useCurrentFrame();
  const chat = ramp(frame, CHAT + 6, CHAT + 30);
  const question = ramp(frame, CHAT + 70, CHAT + 88);
  return (
    <AbsoluteFill style={{ background: color.black }}>
      <div style={{ position: "absolute", left: LEFT, top: 150, width: 1500 }}>
        <Words text="A course says everything three times." at={1} size={84} accent={["three", "times"]} out={CHAT - 10} />
      </div>
      <Panel index={0} label="ON THE BOARD" where="02:06">
        {/* the frozen lecture frame, framed on the handwriting */}
        <div style={{ position: "absolute", left: -1035, top: -40, width: 1920, height: 1080, transform: "scale(1.42)", transformOrigin: "1237px 175px" }}>
          <Footage file="MIT8_01F16_L04v01_360p.mp4" from={126.5} freezeAt={0} glow={0.6} />
        </div>
      </Panel>
      <Panel index={1} label="IN THE TEXTBOOK" where="p. 216">
        <Crop src="pages/p0216@3x.jpg" aspect={1836 / 2376} rect={[0.1305, 0.7535, 0.8641, 0.887]} width={PANEL_W} height={PANEL_H} zoom={0.92} outline={ramp(frame, 96, 118)} />
      </Panel>
      <Panel index={2} label="ON A SLIDE" where="slide 13">
        <Img src={staticFile("slides/slides-ch5-s013.jpg")} style={{ width: PANEL_W, height: PANEL_H, objectFit: "cover", objectPosition: "left top" }} />
      </Panel>

      {/* the chatbot: fluent, and from nowhere */}
      <div style={{ position: "absolute", left: 360, top: 330, width: 1200, opacity: chat, transform: `translateY(${(1 - chat) * 24}px)` }}>
        <Tag size={26} fill={color.dim}>A GENERAL CHATBOT</Tag>
        <div style={{ marginTop: 18, padding: "34px 40px", borderRadius: 22, background: "#1b1a18", border: "1px solid #2e2c28", fontFamily: font.sans, fontSize: 44, lineHeight: 1.36, color: "#cfcac0" }}>
          Newton&rsquo;s second law states that force equals mass times acceleration, F = ma.
        </div>
        <div style={{ marginTop: 26, display: "flex", gap: 18, alignItems: "baseline", fontFamily: font.mono, fontSize: 40, opacity: question }}>
          <span style={{ color: color.dim }}>source:</span>
          <span style={{ color: color.cite, fontSize: 64, opacity: 0.55 + 0.45 * Math.sin(frame / 5) ** 2 }}>?</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
