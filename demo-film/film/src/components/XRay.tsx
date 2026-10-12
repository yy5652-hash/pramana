import React from "react";
import { AbsoluteFill, Img, staticFile, useCurrentFrame } from "remotion";
import film from "../../public/data/film.json";
import { color, easeInOut, font, H, lerp, ramp, W } from "../theme";
import { Tex } from "./Tex";

// One real textbook page, filling the frame, seen two ways. First as printed. Then as the PDF's
// own text layer holds it: every run of text where the file puts it, and a hole wherever a
// formula is, because the formulas are vector drawings with no text behind them. Then the
// holes are filled with what the vision pass stored for them. Positions, text, path counts and
// LaTeX all come from tools/export_data.py; nothing is placed by hand.
type Hole = { r: number[]; paths: number; tex: string; inline: boolean };
const xray = film.xray as { image: string; size: number[]; crop: number[]; lines: { t: string; r: number[] }[]; holes: Hole[] };
const [cx0, cy0, cx1] = xray.crop;
const IMAGE_W = W / (cx1 - cx0);
const IMAGE_H = IMAGE_W * (xray.size[1] / xray.size[0]);
const PAGE = { left: -cx0 * IMAGE_W, top: -cy0 * IMAGE_H };
const INK = "#a9a498";

const Formula: React.FC<{ hole: Hole; index: number; drawingsAt: number; restoreAt: number }> = ({ hole, index, drawingsAt, restoreAt }) => {
  const frame = useCurrentFrame();
  const [x0, y0, x1, y1] = hole.r;
  const [padX, padY] = hole.inline ? [9, 8] : [46, 18];      // a formula set in a line of text gets a tight box
  const box = { left: x0 * W - padX, top: y0 * H - padY, width: (x1 - x0) * W + 2 * padX, height: (y1 - y0) * H + 2 * padY };
  const ink = { left: x0 * W - 8, top: y0 * H - 8, width: (x1 - x0) * W + 16, height: (y1 - y0) * H + 16 };
  const drawn = ramp(frame, drawingsAt + index * 7, drawingsAt + index * 7 + 16);
  const start = restoreAt + index * 12;
  const read = ramp(frame, start, start + 16);
  const flash = read * (1 - ramp(frame, start + 14, start + 44));
  const pulse = 0.45 + 0.55 * Math.sin(frame / 5) ** 2;
  return (
    <>
      <div style={{ position: "absolute", ...box, borderRadius: hole.inline ? 6 : 10, border: `${hole.inline ? 2 : 3}px ${read > 0.5 ? "solid" : "dashed"} ${color.cite}`, opacity: lerp(pulse, 1, Math.max(drawn, read)),
        background: `rgba(240,138,42,${0.1 * read + 0.3 * flash})`, boxShadow: `0 0 ${50 * flash + 16 * read}px rgba(240,138,42,${0.6 * flash + 0.22 * read})` }} />
      {hole.inline ? null : (
        <div style={{ position: "absolute", ...box, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: font.mono, fontSize: 19, letterSpacing: "0.12em", color: color.cite, opacity: pulse * (1 - drawn) * (1 - read) }}>NOTHING HERE</div>
      )}
      {/* the drawing itself: the page's own pixels, light on dark */}
      <div style={{ position: "absolute", ...ink, overflow: "hidden", opacity: drawn * (1 - read), filter: "invert(1) contrast(1.15)", mixBlendMode: "screen" }}>
        <Img src={staticFile(xray.image)} style={{ position: "absolute", left: PAGE.left - ink.left, top: PAGE.top - ink.top, width: IMAGE_W, height: IMAGE_H, maxWidth: "none" }} />
      </div>
      <div style={{ position: "absolute", ...box, display: "flex", alignItems: "center", justifyContent: "center", opacity: read, transform: `scale(${lerp(0.94, 1, read)})` }}>
        <Tex size={hole.inline ? 28 : 33} color={color.chalk} display={!hole.inline}>{hole.tex}</Tex>
      </div>
      {hole.inline ? null : (
        <div style={{ position: "absolute", left: box.left - 420, width: 400, top: box.top + box.height / 2 - 14, textAlign: "right", fontFamily: font.mono, fontSize: 21, letterSpacing: "0.07em", color: color.cite, opacity: Math.max(drawn * (1 - read), read) }}>
          {read > 0.5 ? "read by vision" : `${hole.paths} vector paths`}
        </div>
      )}
    </>
  );
};

export const XRay: React.FC<{ wipeAt: number; drawingsAt: number; restoreAt: number; until: number }> = ({ wipeAt, drawingsAt, restoreAt, until }) => {
  const frame = useCurrentFrame();
  const wipe = ramp(frame, wipeAt, wipeAt + 58, easeInOut);
  const push = lerp(1.045, 1, ramp(frame, 0, until - 30, (t) => t));      // a slow pull back: the whole passage is in frame when the formulas return
  return (
    <AbsoluteFill style={{ background: "#fff", transform: `scale(${push})` }}>
      <Img src={staticFile(xray.image)} style={{ position: "absolute", ...PAGE, width: IMAGE_W, height: IMAGE_H, maxWidth: "none" }} />
      <AbsoluteFill style={{ background: "#0b0a09", clipPath: `inset(0 ${(1 - wipe) * 100}% 0 0)` }}>
        <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
          {xray.lines.map((line, index) => {
            const [x0, y0, x1, y1] = line.r;
            const height = (y1 - y0) * H;
            return (
              <text key={index} x={x0 * W} y={y1 * H - height * 0.24} textLength={(x1 - x0) * W} lengthAdjust="spacingAndGlyphs" fontFamily={font.mono} fontSize={height * 0.84} fill={INK}>
                {line.t}
              </text>
            );
          })}
        </svg>
        {xray.holes.map((hole, index) => <Formula key={index} hole={hole} index={index} drawingsAt={drawingsAt} restoreAt={restoreAt} />)}
      </AbsoluteFill>
      {wipe > 0 && wipe < 1 ? <div style={{ position: "absolute", left: wipe * W - 3, top: 0, width: 6, height: H, background: color.cite, boxShadow: `0 0 46px 12px ${color.cite}` }} /> : null}
    </AbsoluteFill>
  );
};

export const xrayPaths = xray.holes.reduce((total, hole) => total + hole.paths, 0);
export const xrayPage = film.xray.page;
