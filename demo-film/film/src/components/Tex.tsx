import katex from "katex";
import "katex/dist/katex.min.css";
import React from "react";

/** A typeset formula. The film shows LaTeX exactly as the product's vision pass returned it. */
export const Tex: React.FC<{ children: string; size?: number; color?: string; display?: boolean; style?: React.CSSProperties }> = ({ children, size = 64, color = "inherit", display = true, style }) => (
  <span
    style={{ fontSize: size, color, display: display ? "block" : "inline-block", lineHeight: 1.2, ...style }}
    dangerouslySetInnerHTML={{ __html: katex.renderToString(children, { displayMode: display, throwOnError: false, strict: "ignore" }) }}
  />
);
