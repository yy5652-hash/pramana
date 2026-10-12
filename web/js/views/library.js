// Library: what is in the knowledge base, how each piece was read, and a place to add more.
import { api, coursePath, h, icon, kindIcon, rich, state, toast } from "../core.js";
import { openCitation } from "../viewer.js";
import { refreshOverview } from "../main.js";

const kindLabel = { text: "passages", equation: "equations", figure: "figures", slide: "slides", transcript: "spoken passages", frame: "board readings" };

/** One-line preview of a unit: headings and line breaks flattened, cut on a word (never inside maths). */
function preview(text) {
  const flat = text.replace(/^### (.+)$/gm, "$1:").replace(/\$\$/g, "$").replace(/\s+/g, " ").trim();
  if (flat.length <= 260) return flat;
  let cut = flat.slice(0, 260);
  if ((cut.match(/\$/g) || []).length % 2) cut = cut.slice(0, cut.lastIndexOf("$"));
  return `${cut.slice(0, cut.lastIndexOf(" "))} …`;
}

function modalityBar(by) {
  const total = Object.values(by).reduce((a, b) => a + b, 0) || 1;
  return h("div.bar", { title: Object.entries(by).map(([k, v]) => `${k}: ${v}`).join(", ") },
    ["text", "vision", "speech"].map((m) => (by[m] ? h(`i.${m}`, { style: `width:${(by[m] / total) * 100}%` }) : null)));
}

export async function libraryView() {
  const overview = await refreshOverview();
  const stats = overview.stats;
  const units = h("div");
  const total = stats.units;
  const vision = stats.units_by_modality.vision || 0;

  async function showUnits(source) {
    units.replaceChildren(h("div.card", h("p.muted", "Loading…")));
    const rows = await api(coursePath(`/units?source_id=${encodeURIComponent(source.id)}&limit=600`));
    units.replaceChildren(h("div.card", { style: "padding:0" },
      h("div", { style: "padding:14px 18px;display:flex;justify-content:space-between;gap:12px;align-items:baseline" },
        h("h2", source.title), h("span.tiny", `${rows.length} citable units · ${source.licence || ""}`)),
      rows.map((u) => h("div.unit", { onclick: () => openCitation(u) },
        h("div", h("div.small", h("strong", u.place)), h(`span.chip.${u.modality}`, u.kind)),
        h("div", h("div.tiny", u.section || ""), h("div.x", { html: rich(preview(u.text)) }))))));
    units.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const log = h("div.log", { hidden: true });
  const drop = h("div.drop",
    icon("upload"), h("div", { style: "margin-top:6px" }, h("strong", "Add a source"), " · drop a PDF, PPTX or lecture video here, or "),
    h("label.btn.sm", { style: "margin-top:8px" }, "Choose a file", h("input", { type: "file", accept: ".pdf,.pptx,.mp4,.mov,.mkv,.webm", hidden: true, onchange: (e) => upload(e.target.files[0]) })),
    h("div.tiny", { style: "margin-top:8px" }, "No preparation needed: pages are rendered and read with vision, slides are parsed and rendered, video is transcribed and its board is read."),
    log);
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); upload(e.dataTransfer.files[0]); });

  async function upload(file) {
    if (!file) return;
    log.hidden = false;
    log.textContent = `uploading ${file.name}…`;
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`/api${coursePath("/upload")}`, { method: "POST", body: form });
    if (!response.ok) { log.textContent = `upload failed: ${(await response.json()).detail}`; return; }
    let job = await response.json();
    while (job.status === "running") {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      job = await api(`/jobs/${job.id}`);
      log.textContent = job.log.slice(-8).join("\n");
      log.scrollTop = log.scrollHeight;
    }
    if (job.status === "done") {
      toast(`${file.name}: ${job.units} units added and tagged to the course map.`);
      location.reload();
    } else {
      log.textContent += `\nfailed: ${job.error}`;
    }
  }

  return h("div",
    h("div.head", h("div", h("h1", "Library"), h("p", "Everything the tutor is allowed to say comes from here. Each source is cut into citable units that remember their page, slide or timestamp."))),
    h("div.grid.cols-4",
      h("div.card.stat", h("div.n", overview.sources.length), h("div.l", "sources"), h("div.s", Object.entries(stats.sources).map(([k, v]) => `${v} ${k}`).join(" · "))),
      h("div.card.stat", h("div.n", total.toLocaleString()), h("div.l", "citable units"), h("div.s", `${stats.units_tagged} tagged to a concept`)),
      h("div.card.stat", h("div.n", `${Math.round((vision / Math.max(total, 1)) * 100)}%`), h("div.l", "needed vision to read"), h("div.s", "equations, figures, slides with pictures, the board")),
      h("div.card.stat", h("div.n", Object.values(stats.questions_verified).reduce((a, b) => a + b, 0)), h("div.l", "verified questions"), h("div.s", Object.entries(stats.questions_verified).map(([k, v]) => `${v} ${k}`).join(" · ")))),
    h("section",
      h("div.section-title", h("h2", "Sources"),
        h("div.legend", h("span", h("i", { style: "background:#b4ad9c" }), "text layer"), h("span", h("i", { style: "background:#5a6ad0" }), "read by vision"), h("span", h("i", { style: "background:#3aa37c" }), "speech to text"))),
      h("div.card", { style: "padding:0" }, overview.sources.map((s) => h("div.src", { onclick: () => showUnits(s) },
        icon(kindIcon(s.kind)),
        h("div", h("div.t", s.title),
          h("div.tiny", Object.entries(s.by_kind).map(([k, v]) => `${v} ${kindLabel[k] || k}`).join(" · "), s.licence ? ` · ${s.licence}` : ""),
          h("div", { style: "max-width:420px;margin-top:5px" }, modalityBar(s.by_modality))),
        h("span.tiny", `${s.units} units`))))),
    h("section", drop),
    h("section", units));
}
