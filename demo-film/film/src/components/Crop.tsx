import React from "react";
import { Img, staticFile } from "remotion";

/**
 * Shows the part of an image given by `rect` ([x0, y0, x1, y1], 0..1 of the image), filling a
 * box of `width` pixels. `zoom` < 1 shows more context around the region.
 */
export const Crop: React.FC<{
  src: string;
  aspect: number;                              // image width / height
  rect: [number, number, number, number];
  width: number;
  height: number;
  zoom?: number;
  outline?: number;                            // 0..1 opacity of the orange outline on the region
  style?: React.CSSProperties;
}> = ({ src, aspect, rect, width, height, zoom = 1, outline = 0, style }) => {
  const [x0, y0, x1, y1] = rect;
  const imageWidth = (width / (x1 - x0)) * zoom;
  const imageHeight = imageWidth / aspect;
  const cx = ((x0 + x1) / 2) * imageWidth;
  const cy = ((y0 + y1) / 2) * imageHeight;
  const left = width / 2 - cx;
  const top = height / 2 - cy;
  return (
    <div style={{ position: "relative", width, height, overflow: "hidden", background: "#fff", ...style }}>
      <Img src={staticFile(src)} style={{ position: "absolute", left, top, width: imageWidth, height: imageHeight, maxWidth: "none" }} />
      {outline > 0 ? (
        <div style={{ position: "absolute", left: left + x0 * imageWidth - 8, top: top + y0 * imageHeight - 8, width: (x1 - x0) * imageWidth + 16, height: (y1 - y0) * imageHeight + 16,
          borderRadius: 6, boxShadow: `0 0 0 4px rgba(240,138,42,${outline}), 0 0 28px rgba(240,138,42,${outline * 0.5})`, background: `rgba(240,138,42,${outline * 0.12})` }} />
      ) : null}
    </div>
  );
};
