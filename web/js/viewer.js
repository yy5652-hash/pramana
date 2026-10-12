// The source viewer: opens a citation at the exact page (with the passage outlined), slide, or
// second of a lecture, and shows what the system read from it.
import { api, coursePath, h, icon, kindIcon, modalityLabel, rich } from "./core.js";

const pane = () => document.getElementById("viewer");
let current = null;

export function closeViewer() {
  current = null;
  pane().hidden = true;
  pane().replaceChildren();
  document.getElementById("app").classList.remove("with-viewer");
  document.querySelectorAll(".cite.on, .source-row.on").forEach((el) => el.classList.remove("on"));
}

const clock = (seconds) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

function stage(c) {
  const locator = c.locator;
  if (c.media) {
    const start = c.kind === "frame" && locator.t_frame !== undefined ? Math.max(0, locator.t_frame - 4) : locator.t_start;
    const video = h("video", { src: `${c.media}#t=${start}`, controls: true, preload: "metadata", poster: c.asset || undefined });
    video.addEventListener("loadedmetadata", () => { video.currentTime = start; }, { once: true });
    const jump = h("button.btn.sm", { onclick: () => { video.currentTime = start; video.play(); } }, icon("video"), `Play from ${clock(start)}`);
    return h("div", video, h("div", { style: "display:flex;gap:10px;align-items:center;margin-top:10px" }, jump,
      h("span.tiny", `passage ${clock(locator.t_start)} – ${clock(locator.t_end)}`)));
  }
  if (locator.slide !== undefined && !c.page_image) {
    return h("div.slide", h("img", { src: c.asset, alt: `Slide ${locator.slide}` }));
  }
  const page = h("div.page", h("img", { src: c.page_image || c.asset, alt: `Page ${locator.page}` }));
  if (locator.rect) {
    const [x0, y0, x1, y1] = locator.rect;
    const pad = 0.008;
    const mark = h("div.hl", { style: `left:${(x0 - pad) * 100}%;top:${(y0 - pad) * 100}%;width:${(x1 - x0 + 2 * pad) * 100}%;height:${(y1 - y0 + 2 * pad) * 100}%` });
    page.append(mark);
    // Bring the passage to the middle of the viewer. Only the viewer scrolls, never the app.
    page.querySelector("img").addEventListener("load", () => {
      const pane = page.closest(".viewer-body");
      if (pane) pane.scrollTo({ top: Math.max(0, page.offsetTop + mark.offsetTop + mark.offsetHeight / 2 - pane.clientHeight / 2), behavior: "smooth" });
    }, { once: true });
  }
  return page;
}

export function openCitation(c, trigger) {
  current = c.unit_id;
  document.querySelectorAll(".cite.on, .source-row.on").forEach((el) => el.classList.remove("on"));
  document.querySelectorAll(`[data-unit="${CSS.escape(c.unit_id)}"]`).forEach((el) => el.classList.add("on"));
  if (trigger) trigger.classList.add("on");

  const head = h("div.viewer-head",
    h("div", h("div.title", c.source_title), h("div.small", h("span.where", c.place), c.section && c.section !== c.source_title ? ` · ${c.section}` : "")),
    h("button.btn.ghost", { onclick: closeViewer, "aria-label": "Close source viewer" }, icon("close")),
    h("div", { style: "grid-column:1/-1;display:flex;gap:6px;flex-wrap:wrap;margin-top:4px" },
      h("span.chip", icon(kindIcon(c.source_kind), "kind-icon"), c.source_kind),
      h(`span.chip.${c.modality}`, modalityLabel[c.modality] || c.modality),
      c.licence ? h("span.chip", c.licence) : null));

  const read = h("div.read",
    h("h3", icon("eye", "kind-icon"), "What Pramana read here"),
    h("div.passage", { html: rich(c.text || c.excerpt) }));

  const body = h("div.viewer-body", stage(c), read);
  pane().replaceChildren(head, body);
  pane().hidden = false;
  document.getElementById("app").classList.add("with-viewer");

  // A citation carries only an excerpt; fetch the whole unit and, for video, the other channel
  // (what was said alongside what was on the board).
  api(coursePath(`/units/${encodeURIComponent(c.unit_id)}`)).then((unit) => {
    if (current !== c.unit_id) return;
    read.querySelector(".passage").innerHTML = rich(unit.text);
    if (unit.sibling_text) {
      body.append(h("div.read",
        h("h3", icon(c.kind === "frame" ? "mic" : "eye", "kind-icon"), c.kind === "frame" ? "Said at this moment" : "On the board at this moment"),
        h("div.passage", { html: rich(unit.sibling_text) })));
    }
  }).catch(() => {});
}

/** A row describing one source of an answer; clicking opens it. */
export function sourceRow(c, number) {
  const row = h("button.source-row", { "data-unit": c.unit_id, onclick: () => openCitation(c, row) },
    h("span.n", number ?? "•"),
    h("span", h("div.t", `${c.source_title} · ${c.place}`), h("div.x", { html: rich(c.excerpt) })),
    icon(kindIcon(c.source_kind), "kind-icon"));
  return row;
}

export const isOpen = () => current;
