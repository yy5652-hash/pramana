import React from "react";
import { AbsoluteFill, Img, interpolate, Sequence, staticFile, useCurrentFrame } from "remotion";
import { Count } from "../components/Count";
import { Dots, SPEECH } from "../components/Dots";
import { Footage } from "../components/Footage";
import { Lower } from "../components/Lower";
import { Reticle } from "../components/Reticle";
import { Tex } from "../components/Tex";
import { Tag, Words } from "../components/Type";
import { XRay, xrayPage, xrayPaths } from "../components/XRay";
import film from "../../public/data/film.json";
import { clock, color, font, ramp, sec } from "../theme";

// Why the product reads with vision, in four beats, all on real material:
//   1. a textbook page, then the same page as its file's text layer holds it (no formulas),
//      then the formulas the vision pass read back;
//   2. a slide whose figure it described;
//   3. a lecture, where it read the glass board;
//   4. the knowledge base that came out, one dot per citable piece.
export const S5_SECONDS = 31;
const T = { wipe: 2.5, drawings: 6.2, restore: 9.5, slide: 11.5, board: 14.0, stats: 20.6 };
const stats = film.stats;

// ---- 2: the slide ---------------------------------------------------------------------------
const slide = film.slide_read;
const SLIDE = { left: 96, top: 120, width: 1120, height: 840 };
const GRAPH = [0.565, 0.07, 0.9, 0.5];        // where graph (c) sits on the slide, as fractions of it
const graphBox: [number, number, number, number] = [SLIDE.left + GRAPH[0] * SLIDE.width, SLIDE.top + GRAPH[1] * SLIDE.height, SLIDE.left + GRAPH[2] * SLIDE.width, SLIDE.top + GRAPH[3] * SLIDE.height];
const graphSentence = (slide.figure.split(". ").find((sentence) => sentence.startsWith("Diagram (c)")) ?? "").replace(/\.$/, "");
const slideFormulas = slide.equations.filter((equation) => equation.includes("\\mu"));

const SlideBeat: React.FC = () => {
  const frame = useCurrentFrame();
  const enter = ramp(frame, 0, 10);
  return (
    <AbsoluteFill style={{ background: color.black, opacity: enter }}>
      <div style={{ position: "absolute", ...SLIDE, borderRadius: 14, overflow: "hidden", boxShadow: "0 40px 120px rgba(0,0,0,.8)", transform: `scale(${0.985 + 0.015 * enter})` }}>
        <Img src={staticFile("slides/slides-ch6-s015.jpg")} style={{ width: "100%", height: "100%" }} />
      </div>
      <Reticle box={graphBox} at={8} />
      <div style={{ position: "absolute", left: 1290, top: 136, width: 540 }}>
        <Tag at={6} size={25} fill={color.dim}>{`SLIDE ${slide.locator.slide} · CHAPTER 6 DECK`}</Tag>
        <Tag at={14} size={25} style={{ marginTop: 10 }}>ITS FIGURE, DESCRIBED BY VISION</Tag>
        <div style={{ fontFamily: font.serif, fontSize: 28, lineHeight: 1.42, color: "#cfcabf", marginTop: 30, opacity: ramp(frame, 18, 32) }}>“{graphSentence}.”</div>
        <div style={{ marginTop: 40 }}>
          {slideFormulas.map((equation, index) => (
            <div key={equation} style={{ opacity: ramp(frame, 28 + index * 7, 40 + index * 7), marginBottom: 18 }}>
              <Tex display={false} size={index === slideFormulas.length - 1 ? 62 : 44} color={index === slideFormulas.length - 1 ? color.cite : color.chalk}>{equation}</Tex>
            </div>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ---- 3: the board ---------------------------------------------------------------------------
// MIT 8.01SC lecture 6.2. From 2:16 the lecturer says "this coefficient of static friction is
// slightly bigger than the coefficient of kinetic friction" and writes it; the last stroke lands at 2:20.
const board = film.board_read;
const BOARD_SOURCE = 135.4;
const WRITTEN = sec(140.3 - BOARD_SOURCE);
const BOARD_BOX: [number, number, number, number] = [1086, 318, 1866, 852];
const BOARD_FRAMES = sec(T.stats - T.board);

const BoardBeat: React.FC = () => {
  const frame = useCurrentFrame();
  const last = board.equations.length - 1;
  return (
    <AbsoluteFill style={{ background: color.black }}>
      <Footage
        file="MIT8_01F16_L06v02_360p.mp4"
        from={BOARD_SOURCE}
        volume={(f) => interpolate(f, [12, 22, BOARD_FRAMES - 14, BOARD_FRAMES - 2], [0, 1.25, 1.25, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })}
        style={{ opacity: ramp(frame, 0, 8) }}
      />
      <div style={{ position: "absolute", left: 96, bottom: 84, opacity: ramp(frame, 6, 20) * (1 - ramp(frame, BOARD_FRAMES - 10, BOARD_FRAMES)) }}>
        <div style={{ fontFamily: font.mono, fontSize: 30, color: color.dim, letterSpacing: "0.06em" }}>MIT 8.01 · LECTURE 6.2</div>
        <div style={{ fontFamily: font.mono, fontSize: 58, color: frame >= WRITTEN ? color.cite : color.chalk, marginTop: 6 }}>{clock(BOARD_SOURCE + frame / 30)}</div>
      </div>
      <Reticle box={BOARD_BOX} at={22} out={BOARD_FRAMES - 12} />
      <div style={{ position: "absolute", left: 104, top: 112, width: 880, opacity: 1 - ramp(frame, BOARD_FRAMES - 10, BOARD_FRAMES) }}>
        <Tag at={34} size={26}>READ FROM THE GLASS · BY A VISION MODEL</Tag>
        <div style={{ marginTop: 30 }}>
          {board.equations.map((equation, index) => {
            const at = index === last ? WRITTEN : 44 + index * 20;
            const t = ramp(frame, at, at + 16);
            return (
              <div key={equation} style={{ opacity: t, transform: `translateY(${(1 - t) * 12}px)`, marginBottom: index === last ? 0 : 18, marginTop: index === last ? 34 : 0 }}>
                <Tex size={index === last ? 100 : 54} color={index === last ? color.cite : color.chalk} style={{ textAlign: "left" }}>{equation}</Tex>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ---- 4: what came out -----------------------------------------------------------------------
const StatsBeat: React.FC = () => {
  const frame = useCurrentFrame();
  const VISION = sec(4.6), HEARD = sec(6.9), LINE = sec(7.8);
  const legend = (at: number, tone: string, text: string) => (
    <span style={{ opacity: ramp(frame, at, at + 14), marginRight: 34 }}>
      <i style={{ display: "inline-block", width: 14, height: 14, borderRadius: 7, background: tone, marginRight: 10 }} />
      {text}
    </span>
  );
  return (
    <AbsoluteFill style={{ background: color.black, opacity: ramp(frame, 0, 10) }}>
      <div style={{ position: "absolute", left: 150, top: 150 }}>
        <Dots marks={film.unit_marks} size={640} at={3} visionAt={VISION} speechAt={HEARD} />
        <div style={{ fontFamily: font.mono, fontSize: 22, color: color.dim, letterSpacing: "0.04em", marginTop: 26, whiteSpace: "nowrap" }}>
          {legend(60, "#b9b4a9", "the file's own text")}
          {legend(VISION, color.cite, "read by vision")}
          {legend(HEARD, SPEECH, "speech")}
        </div>
      </div>
      <div style={{ position: "absolute", left: 930, top: 120, width: 900 }}>
        <Count size={132} value={stats.units} at={6} frames={48} label="citable pieces of one course" note={`${stats.sources.textbook} textbook · ${stats.sources.slides} slide decks · ${stats.sources.video} lectures · one dot each`} />
        <div style={{ height: 44 }} />
        <Count size={132} value={Math.round(film.vision_share * 100)} suffix="%" at={VISION} fill={color.cite} label="could only be read with vision" note={`${stats.units_by_modality.vision} of ${stats.units}: formulas, figures, slides, the board`} />
        <div style={{ height: 44 }} />
        <Count size={132} value={stats.units_by_modality.speech} at={HEARD} fill={SPEECH} label="passages heard, not read" note="speech to text, timed to the second" />
      </div>
      <div style={{ position: "absolute", left: 150, top: 944, width: 1620 }}>
        <Words text="Each one remembers its page, its slide, or its second." at={LINE} size={52} fill={color.dim} accent={["page", "slide", "second"]} />
      </div>
    </AbsoluteFill>
  );
};

export const S5_FRAMES = sec(S5_SECONDS);

export const S5Vision: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: color.black }}>
      <Sequence durationInFrames={sec(T.slide)}>
        <AbsoluteFill style={{ opacity: ramp(frame, 0, 14) * (1 - ramp(frame, sec(T.slide) - 8, sec(T.slide))) }}>
          <XRay wipeAt={sec(T.wipe)} drawingsAt={sec(T.drawings)} restoreAt={sec(T.restore)} until={sec(T.slide)} />
        </AbsoluteFill>
        <Lower top right from={0.5} to={T.wipe + 0.2} label={`UNIVERSITY PHYSICS, VOL. 1 · p. ${xrayPage}`} value="a page of the textbook" tone={color.chalk} />
        <Lower top right from={T.wipe + 1.0} to={T.drawings} label="THE SAME PAGE, AS THE FILE'S TEXT" value="no formulas in it" />
        <Lower top right from={T.drawings + 0.2} to={T.restore - 0.1} label={`${xrayPaths} VECTOR PATHS · NO TEXT BEHIND THEM`} value="they are drawings" />
        <Lower top right from={T.restore + 0.3} to={T.slide - 0.1} label="READ WITH A VISION MODEL" value="every formula, as LaTeX" />
      </Sequence>
      <Sequence from={sec(T.slide)} durationInFrames={sec(T.board - T.slide)}>
        <SlideBeat />
      </Sequence>
      <Sequence from={sec(T.board)} durationInFrames={BOARD_FRAMES}>
        <BoardBeat />
      </Sequence>
      {/* the numbers come up over the last frames of the lecture: no black between them */}
      <Sequence from={sec(T.stats) - 9}>
        <StatsBeat />
      </Sequence>
    </AbsoluteFill>
  );
};
