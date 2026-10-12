import React from "react";
import { AbsoluteFill, Freeze, OffthreadVideo, staticFile, useCurrentFrame, useVideoConfig } from "remotion";

/**
 * Real lecture footage (MIT OpenCourseWare 8.01SC, 640x360). It is shot on a lightboard, so the
 * picture is light on black: scaled up and laid on the film's black stage it needs no frame.
 * A blurred copy screened over itself gives the handwriting its glow and hides the upscale.
 */
export const Footage: React.FC<{
  file: string;
  from: number;             // seconds into the source at this sequence's first frame
  volume?: number | ((frame: number) => number);
  glow?: number;
  freezeAt?: number;        // sequence frame from which the picture holds still
  style?: React.CSSProperties;
}> = ({ file, from, volume = 0, glow = 0.5, freezeAt, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const src = staticFile(`footage/${file}`);
  const fill: React.CSSProperties = { position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" };
  const picture = (
    <AbsoluteFill>
      <OffthreadVideo src={src} startFrom={Math.round(from * fps)} volume={volume} style={{ ...fill, filter: "contrast(1.1) saturate(1.05)" }} />
      {glow > 0 ? (
        <AbsoluteFill style={{ mixBlendMode: "screen", opacity: glow }}>
          <OffthreadVideo src={src} startFrom={Math.round(from * fps)} muted style={{ ...fill, filter: "blur(16px) brightness(1.5) contrast(1.35)" }} />
        </AbsoluteFill>
      ) : null}
    </AbsoluteFill>
  );
  return <AbsoluteFill style={style}>{freezeAt !== undefined && frame >= freezeAt ? <Freeze frame={freezeAt}>{picture}</Freeze> : picture}</AbsoluteFill>;
};
