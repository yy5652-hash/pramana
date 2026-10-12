// Shared helpers: DOM construction, API calls, app state, and safe rendering of text with maths.

export const state = {
  course: null,        // {id, title}
  overview: null,      // sources, topics, concepts, prereqs, stats
  students: [],
  student: null,       // {id, name}
  language: localStorage.getItem("pramana.language") || "en",
  allowOutside: localStorage.getItem("pramana.outside") === "1",
};

/** h("div.card", {onclick}, child, ...) -> element. Strings become text nodes; null is skipped. */
export function h(spec, attrs, ...children) {
  // The second argument is attributes only when it is a plain object; anything else is a child.
  if (attrs !== null && attrs !== undefined && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) {
    children.unshift(attrs);
    attrs = null;
  }
  const [tag, ...classes] = spec.split(".");
  const svg = ["svg", "g", "path", "rect", "text", "line", "circle", "polyline", "tspan"].includes(tag);
  const el = svg ? document.createElementNS("http://www.w3.org/2000/svg", tag) : document.createElement(tag || "div");
  if (classes.length) el.setAttribute("class", classes.join(" "));
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "class") el.setAttribute("class", `${el.getAttribute("class") || ""} ${value}`.trim());
    else if (key === "html") el.innerHTML = value;
    else if (key in el && !svg && key !== "list") el[key] = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

/** Replace an element's children, with the same rules as h(): arrays are flattened, null and false are skipped. */
export function fill(el, ...children) {
  el.replaceChildren(...children.flat(Infinity)
    .filter((child) => child !== null && child !== undefined && child !== false)
    .map((child) => (child instanceof Node ? child : document.createTextNode(String(child)))));
  return el;
}

export async function api(path, body, method) {
  const options = body === undefined ? { method: method || "GET" } : {
    method: method || "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  };
  const response = await fetch(`/api${path}`, options);
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail || detail; } catch { /* not JSON */ }
    throw new Error(detail);
  }
  return response.json();
}

export const coursePath = (rest = "") => `/courses/${state.course.id}${rest}`;
export const studentPath = (rest = "") => coursePath(`/students/${state.student.id}${rest}`);

const escapeHtml = (text) => text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function tex(source, display) {
  try {
    return window.katex.renderToString(source, { displayMode: display, throwOnError: false, strict: "ignore" });
  } catch {
    return `<code>${escapeHtml(source)}</code>`;
  }
}

/** Text with $inline$ / $$display$$ maths, **bold** and "### headings" -> safe HTML. */
export function rich(text) {
  if (!text) return "";
  const parts = String(text).split(/(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$)/g);
  return parts.map((part) => {
    if (part.startsWith("$$") && part.endsWith("$$") && part.length > 4) return tex(part.slice(2, -2).trim(), true);
    if (part.startsWith("$") && part.endsWith("$") && part.length > 2) return tex(part.slice(1, -1), false);
    return escapeHtml(part)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/^### (.+)$/gm, "<strong>$1</strong>")
      .replace(/\n{2,}/g, "<br><br>")
      .replace(/\n/g, "<br>");
  }).join("");
}

export const richEl = (spec, text) => h(spec, { html: rich(text) });

export const pct = (value) => `${Math.round(value * 100)}%`;
export const levelColor = { weak: "var(--weak)", developing: "var(--developing)", mastered: "var(--mastered)", unknown: "var(--unknown)" };
export const levelOf = (c) => c.level;

/** Fill colour for a mastery value, so the map and bars agree. */
export function masteryColor(concept) {
  return levelColor[concept.level] || levelColor.unknown;
}

const paths = {
  book: '<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M19 19v2H6"/>',
  slides: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M12 16v4M8 20h8"/>',
  video: '<rect x="3" y="5" width="13" height="14" rx="2"/><path d="m16 10 5-3v10l-5-3z"/>',
  map: '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="8" r="2.5"/><circle cx="10" cy="18" r="2.5"/><path d="m8.3 7 7.3.7M7 8.3l2.2 7.4M16.5 10l-5 6.4"/>',
  chat: '<path d="M4 5h16v11H9l-5 4z"/>',
  quiz: '<path d="M9 11l2 2 4-4"/><rect x="4" y="4" width="16" height="16" rx="3"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  proof: '<path d="M12 3l7 3v6c0 4.5-3 7.6-7 9-4-1.4-7-4.5-7-9V6z"/><path d="m9 12 2 2 4-4"/>',
  library: '<path d="M4 4v16M9 4v16M14 5l5 14"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  speaker: '<path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16 9a4 4 0 0 1 0 6"/>',
  send: '<path d="M4 12 20 4l-6 16-3-7z"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>',
  eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
};

export function icon(name, cls = "") {
  const el = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  el.setAttribute("viewBox", "0 0 24 24");
  el.setAttribute("fill", "none");
  el.setAttribute("stroke", "currentColor");
  el.setAttribute("stroke-width", "1.7");
  el.setAttribute("stroke-linecap", "round");
  el.setAttribute("stroke-linejoin", "round");
  if (cls) el.setAttribute("class", cls);
  el.innerHTML = paths[name] || "";
  return el;
}

export const kindIcon = (sourceKind) => ({ textbook: "book", slides: "slides", video: "video" }[sourceKind] || "book");
export const modalityLabel = { text: "text layer", vision: "read by vision", speech: "speech to text" };

export function toast(message) {
  const el = h("div", { style: "position:fixed;left:50%;bottom:26px;transform:translateX(-50%);background:#1d1c1a;color:#f5f2ea;padding:10px 16px;border-radius:9px;z-index:50;max-width:70vw;box-shadow:0 8px 30px rgba(0,0,0,.25)" }, message);
  document.body.append(el);
  setTimeout(() => el.remove(), 4200);
}

/** Read text aloud with the browser's speech synthesis (the "audio brief"). Maths markup is dropped. */
export function speak(text, language = "en") {
  if (!("speechSynthesis" in window)) return toast("This browser has no speech synthesis.");
  window.speechSynthesis.cancel();
  const plain = text.replace(/\$\$?[^$]*\$\$?/g, " (formula) ").replace(/[*#]/g, "");
  const utterance = new SpeechSynthesisUtterance(plain);
  utterance.lang = language === "en" ? "en-IN" : "hi-IN";
  utterance.rate = 1.0;
  window.speechSynthesis.speak(utterance);
}
