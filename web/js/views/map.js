// Course map: topics as columns, concepts as nodes, prerequisites as edges, coloured by the
// student's mastery. Built from the knowledge base; nothing here is drawn by hand.
import { api, coursePath, h, icon, levelColor, pct, state, studentPath } from "../core.js";
import { sourceRow } from "../viewer.js";

const NODE_W = 196, NODE_H = 50, GAP_X = 64, GAP_Y = 16, TOP = 44, LEFT = 20;

function wrap(name, max = 24) {
  const words = name.split(" ");
  const lines = [""];
  for (const word of words) {
    if ((lines[lines.length - 1] + " " + word).trim().length > max && lines.length < 2) lines.push(word);
    else lines[lines.length - 1] = (lines[lines.length - 1] + " " + word).trim();
  }
  if (lines[1] && lines[1].length > max) lines[1] = lines[1].slice(0, max - 1) + "…";
  return lines;
}

export async function mapView() {
  const { topics, concepts, prereqs } = state.overview;
  const snapshot = (await api(studentPath())).concepts;
  const byId = Object.fromEntries(snapshot.map((c) => [c.concept_id, c]));
  const position = {};
  let height = 0;
  topics.forEach((topic, column) => {
    concepts.filter((c) => c.topic_id === topic.id).forEach((concept, row) => {
      position[concept.id] = { x: LEFT + column * (NODE_W + GAP_X), y: TOP + row * (NODE_H + GAP_Y) };
      height = Math.max(height, TOP + (row + 1) * (NODE_H + GAP_Y));
    });
  });
  const width = LEFT * 2 + topics.length * (NODE_W + GAP_X) - GAP_X;
  const detail = h("div.card", h("p.muted", "Select a concept to see what it rests on, where it is taught, and how you are doing on it."));
  const svg = h("svg", { width, height: height + 10, viewBox: `0 0 ${width} ${height + 10}`, role: "img", "aria-label": "Concept map" });

  topics.forEach((topic, column) => {
    svg.append(h("text.topic-label", { x: LEFT + column * (NODE_W + GAP_X), y: 24 }, topic.title.length > 30 ? topic.title.slice(0, 29) + "…" : topic.title));
  });

  const edges = prereqs.filter((e) => position[e.concept_id] && position[e.requires_id]).map((edge) => {
    const from = position[edge.requires_id], to = position[edge.concept_id];
    const sameColumn = from.x === to.x;
    let d;
    if (sameColumn) {
      // Within a topic, arc out to the left so the edge does not run behind the nodes.
      const x = from.x, y1 = from.y + NODE_H / 2, y2 = to.y + NODE_H / 2;
      d = `M${x},${y1} C${x - 26},${y1} ${x - 26},${y2} ${x},${y2}`;
    } else {
      const x1 = from.x + NODE_W, y1 = from.y + NODE_H / 2, x2 = to.x, y2 = to.y + NODE_H / 2;
      const mid = (x1 + x2) / 2;
      d = `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`;
    }
    const path = h("path.edge", { d, "data-from": edge.requires_id, "data-to": edge.concept_id });
    svg.append(path);
    return path;
  });

  function select(concept) {
    svg.querySelectorAll(".node").forEach((n) => n.classList.toggle("on", n.dataset.id === concept.id));
    edges.forEach((p) => p.classList.toggle("on", p.dataset.from === concept.id || p.dataset.to === concept.id));
    const s = byId[concept.id];
    const requires = prereqs.filter((e) => e.concept_id === concept.id).map((e) => concepts.find((c) => c.id === e.requires_id));
    const unlocks = prereqs.filter((e) => e.requires_id === concept.id).map((e) => concepts.find((c) => c.id === e.concept_id));
    const sources = h("div.sources", h("p.tiny", "Loading sources…"));
    detail.replaceChildren(
      h("div", { style: "display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap" },
        h("div", { style: "max-width:70ch" }, h("h2", concept.name), h("p.muted", { style: "margin-top:4px" }, concept.description)),
        h("div", { style: "display:flex;gap:8px;align-items:center" },
          h(`span.chip.${s.level}`, s.n_obs ? `${s.level} · ${pct(s.mastery)}` : "not assessed"),
          h("a.btn.sm", { href: `#/lessons/${concept.id}` }, icon("video"), "Lesson"),
          h("a.btn.sm.primary", { href: "#/practice" }, "Practise", icon("arrow")))),
      h("div.grid.cols-2", { style: "margin-top:8px" },
        h("div", h("h3", "Rests on"), requires.length ? requires.map((c) => h("div.small", h(`span.dot.${byId[c.id].level}`), ` ${c.name}`)) : h("div.small.muted", "Nothing: this is a starting point.")),
        h("div", h("h3", "Unlocks"), unlocks.length ? unlocks.map((c) => h("div.small", h(`span.dot.${byId[c.id].level}`), ` ${c.name}`)) : h("div.small.muted", "Nothing further in this course."))),
      h("h3", { style: "margin-top:12px" }, `Taught in ${concept.units} places · ${concept.questions} verified questions`),
      sources);
    api(coursePath(`/units?concept_id=${encodeURIComponent(concept.id)}&limit=60`)).then((units) => {
      const seen = new Set();
      const picks = units.filter((u) => (seen.has(u.source_kind) ? false : seen.add(u.source_kind)));
      sources.replaceChildren(...(picks.length ? picks.map((c) => sourceRow(c)) : [h("p.tiny", "No tagged units.")]));
    });
  }

  concepts.forEach((concept) => {
    const p = position[concept.id];
    if (!p) return;
    const s = byId[concept.id];
    const lines = wrap(concept.name);
    const node = h("g.node", { "data-id": concept.id, transform: `translate(${p.x},${p.y})`, onclick: () => select(concept), tabindex: 0, role: "button", "aria-label": concept.name },
      h("rect", { width: NODE_W, height: NODE_H }),
      h("rect", { width: 6, height: NODE_H, style: `fill:${levelColor[s.level]};stroke:none`, rx: 3 }),
      lines.map((line, i) => h("text", { x: 16, y: lines.length === 1 ? 30 : 21 + i * 16 }, line)),
      h("text.pct", { x: NODE_W - 10, y: NODE_H - 9, "text-anchor": "end" }, s.n_obs ? pct(s.mastery) : ""));
    node.addEventListener("keydown", (event) => { if (event.key === "Enter") select(concept); });
    svg.append(node);
  });

  return h("div",
    h("div.head", h("div", h("h1", "Course map"), h("p", `${topics.length} topics, ${concepts.length} concepts and ${prereqs.length} prerequisite links, extracted from the outline of your sources. Colour shows ${state.student.name}'s mastery.`)),
      h("div.legend", ["mastered", "developing", "weak", "unknown"].map((l) => h("span", h(`i.dot.${l}`), l)))),
    h("div.map-wrap", svg),
    h("section", detail));
}
