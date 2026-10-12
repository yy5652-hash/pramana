// Evidence: the system's own measurements, read from evaluation/results/*.json.
// Nothing on this page is typed in by hand; rerun the evaluation and the page changes.
import { api, coursePath, h, state } from "../core.js";

const fmt = (v, digits = 2) => (v === null || v === undefined ? "—" : Number(v).toFixed(digits));
const policyColor = { adaptive: "var(--cite)", random: "var(--ink-3)", sequential: "var(--indigo)" };
const metricLabel = {
  faithfulness: ["Faithfulness", "claims in the answer that the retrieved context supports"],
  answer_relevancy: ["Answer relevancy", "how directly the answer addresses the question"],
  llm_context_precision_with_reference: ["Context precision", "retrieved passages that are relevant, weighted by rank"],
  context_recall: ["Context recall", "claims of the reference answer found in the retrieved context"],
};

function bar(value, ci, color = "var(--ink)") {
  const track = h("div.track", h("i", { style: `width:${Math.max(0, Math.min(1, value || 0)) * 100}%;background:${color}` }));
  if (ci) {
    const low = Math.max(0, value - ci) * 100, high = Math.min(1, value + ci) * 100;
    track.append(h("i", { style: `left:${low}%;width:${high - low}%;top:4px;bottom:4px;background:rgba(0,0,0,.35);border-radius:0` }));
  }
  return track;
}

function lineChart(series, { yMin = 0, yMax = 1, yLabel = "", xLabel = "session" } = {}) {
  const W = 560, H = 250, L = 46, R = 14, T = 14, B = 34;
  const n = Math.max(...series.map((s) => s.points.length));
  const x = (i) => L + (i / Math.max(n - 1, 1)) * (W - L - R);
  const y = (v) => T + (1 - (v - yMin) / (yMax - yMin)) * (H - T - B);
  const svg = h("svg.chart", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  for (let tick = 0; tick <= 4; tick += 1) {
    const value = yMin + (tick / 4) * (yMax - yMin);
    svg.append(h("line.gridline", { x1: L, x2: W - R, y1: y(value), y2: y(value) }), h("text", { x: L - 8, y: y(value) + 4, "text-anchor": "end" }, value.toFixed(2)));
  }
  for (let i = 0; i < n; i += 1) svg.append(h("text", { x: x(i), y: H - 14, "text-anchor": "middle" }, String(i + 1)));
  svg.append(h("text", { x: (L + W - R) / 2, y: H - 1, "text-anchor": "middle" }, xLabel), h("text", { x: 12, y: 12 }, yLabel));
  for (const s of series) {
    if (s.band) {
      const upper = s.points.map((p, i) => `${x(i)},${y(p + s.band[i])}`);
      const lower = s.points.map((p, i) => `${x(i)},${y(p - s.band[i])}`).reverse();
      svg.append(h("path", { d: `M${upper.concat(lower).join(" L")} Z`, style: `fill:${s.color};opacity:.13` }));
    }
    svg.append(h("polyline", { points: s.points.map((p, i) => `${x(i)},${y(p)}`).join(" "), style: `fill:none;stroke:${s.color};stroke-width:2.2` }));
    s.points.forEach((p, i) => svg.append(h("circle", { cx: x(i), cy: y(p), r: 3, style: `fill:${s.color}` })));
  }
  return h("div", svg, h("div.legend", series.map((s) => h("span", h("i", { style: `background:${s.color}` }), s.name))));
}

function ragasCard(r) {
  return h("div.card", h("h2", "Answer quality (RAGAS)"),
    h("p.muted.small", `${r.framework} on ${r.n_scored} answered in-material questions, top ${r.contexts_per_question} contexts each. Judge: ${r.judge_models.join(", ")}. Tutor: ${r.tutor_models.join(", ")}. Bars show the mean; the dark band is a 95 % interval.`),
    Object.entries(r.metrics).map(([name, m]) => h("div.metric", { title: (metricLabel[name] || [name, ""])[1] },
      h("div", h("strong", (metricLabel[name] || [name])[0]), h("div.tiny", (metricLabel[name] || ["", ""])[1])),
      bar(m.mean, m.ci95, "var(--cite)"), h("div.num", { style: "text-align:right" }, fmt(m.mean), h("span.tiny", ` ±${fmt(m.ci95)}`)))));
}

function groundingCard(g) {
  const r = g.refusal, s = g.citation_support, loc = g.citation_location.answers_citing_gold_location;
  return h("div.card", h("h2", "Grounding"),
    h("h3", "Declining what the material does not cover"),
    h("table", { style: "margin:6px 0 4px" },
      h("thead", h("tr", h("th", ""), h("th.r", "answered"), h("th.r", "declined"))),
      h("tbody",
        h("tr", h("td", `In the material (${g.n_in_material})`), h("td.r.num", r.in_material_answered), h("td.r.num", r.in_material_declined)),
        h("tr", h("td", `Not in the material (${g.n_off_material})`), h("td.r.num", r.off_material_answered), h("td.r.num", r.off_material_declined)))),
    h("p.tiny", `Other subjects: ${r.by_distance.far.declined}/${r.by_distance.far.n} declined. Physics the chapters do not teach: ${r.by_distance.near.declined}/${r.by_distance.near.n} declined.`),
    h("h3", { style: "margin-top:12px" }, "Do the cited sources say what the sentence says?"),
    h("div.bar", { style: "height:12px;margin:8px 0 4px" },
      h("i", { style: `width:${s.fully_supported * 100}%;background:var(--mastered)` }),
      h("i", { style: `width:${s.partly_supported * 100}%;background:var(--developing)` }),
      h("i", { style: `width:${s.unsupported * 100}%;background:var(--weak)` })),
    h("p.tiny", `${s.segments_judged} answer segments judged by a second model: ${fmt(s.fully_supported * 100, 0)}% fully supported, ${fmt(s.partly_supported * 100, 0)}% partly, ${fmt(s.unsupported * 100, 0)}% unsupported.`),
    h("h3", { style: "margin-top:12px" }, "Citing the known location"),
    h("p.small", `${fmt(loc.mean * 100, 0)}% of answers cite the exact page, slide or lecture moment the question was written from (n = ${loc.n}). This is strict: citing the same fact in another source counts as a miss.`));
}

function retrievalCard(r) {
  const rows = Object.entries(r.full.modes);
  const cell = (m) => h("td.r.num", fmt(m.mean), h("span.tiny", ` ±${fmt(m.ci95)}`));
  return h("div.card", h("h2", "Retrieval against known locations"),
    h("p.muted.small", `${r.n_questions} questions whose answer has a known page, slide or lecture moment. A hit means the result at that rank sits at that location.`),
    h("table",
      h("thead", h("tr", h("th", "Retriever"), h("th.r", "hit@1"), h("th.r", "hit@3"), h("th.r", "hit@6"), h("th.r", "MRR"))),
      h("tbody",
        rows.map(([name, m]) => h("tr", h("td", name === "hybrid + rerank" ? h("strong", name) : name), cell(m["hit@1"]), cell(m["hit@3"]), cell(m["hit@6"]), cell(m.mrr))),
        r.no_vision ? h("tr", { style: "background:#fbeceb" }, h("td", "Without vision ingestion"), ...["hit@1", "hit@3", "hit@6", "mrr"].map((k) => cell(r.no_vision.modes["hybrid + rerank"][k]))) : null)),
    h("h3", { style: "margin-top:12px" }, "By where the answer lives (hybrid + rerank, hit@3)"),
    Object.entries(r.full.by_stratum).map(([name, m]) => h("div.metric",
      h("div", name, h("span.tiny", ` · n=${m["hit@3"].n}`)), bar(m["hit@3"].mean), h("div.num", { style: "text-align:right" }, fmt(m["hit@3"].mean)),
      r.no_vision && r.no_vision.by_stratum[name] ? h("div.tiny", { style: "grid-column:2/-1" }, `without vision: ${fmt(r.no_vision.by_stratum[name]["hit@3"].mean)}`) : null)));
}

function simulationCard(sim) {
  const root = h("div.card");
  function render(kind) {
    const block = sim.learners[kind];
    const cells = Object.values(block.cells);
    const profiles = [...new Set(cells.map((c) => c.profile))];
    const pooled = (policy, key) => {
      const own = cells.filter((c) => c.policy === policy);
      return own[0].per_session.map((_, i) => own.reduce((a, c) => a + (key === "auc" ? (c.per_session[i].auc ?? 0.5) : c.per_session[i][key].mean), 0) / own.length);
    };
    root.replaceChildren(
      h("div.section-title", h("h2", "Simulated students"),
        h("div.seg", { style: "margin-left:auto" }, [["structured", "Structured learner"], ["flat", "Flat learner"]].map(([id, label]) =>
          h(`button${id === kind ? ".on" : ""}`, { onclick: () => render(id) }, label)))),
      h("p.muted.small", `${sim.students_per_cell} simulated students per profile and policy, ${sim.sessions} daily sessions of ${sim.questions_per_session} questions from the real bank (${sim.bank} verified questions, ${sim.concepts} concepts). Answers come from a logistic item-response model, not from the learner model's own assumptions. `,
        kind === "structured" ? "Structured learner: learning is slower without prerequisites and from badly matched difficulty." : "Flat learner: both of those effects are switched off, so sequencing cannot help by construction."),
      h("div.grid.cols-2",
        h("div", h("h3", "True proficiency, session by session"), lineChart(["adaptive", "sequential", "random"].map((p) => ({ name: p, color: policyColor[p], points: pooled(p, "true_mean") })), { yMin: 0.2, yMax: 0.8, yLabel: "mean true proficiency" })),
        h("div", h("h3", "Does the model know the student better with more data?"), lineChart([
          { name: "AUC of predicted correctness (adaptive)", color: "var(--cite)", points: pooled("adaptive", "auc") },
          { name: "rank correlation, estimate vs truth (adaptive)", color: "var(--indigo)", points: pooled("adaptive", "spearman") },
        ], { yMin: 0, yMax: 1, yLabel: "" }))),
      h("h3", { style: "margin-top:14px" }, "Gain in true proficiency by exam day (mean ± 95 % interval)"),
      h("table",
        h("thead", h("tr", h("th", "Student profile"), h("th.r", "start"), h("th.r", "adaptive"), h("th.r", "sequential"), h("th.r", "random"))),
        h("tbody",
          profiles.map((profile) => {
            const get = (policy) => block.cells[`${profile}|${policy}`];
            const best = Math.max(...["adaptive", "sequential", "random"].map((p) => get(p).gain.mean));
            return h("tr", h("td", profile), h("td.r.num", fmt(get("adaptive").start_mean)),
              ["adaptive", "sequential", "random"].map((p) => h("td.r.num", { style: get(p).gain.mean === best ? "font-weight:650" : "" }, `+${fmt(get(p).gain.mean, 3)}`, h("span.tiny", ` ±${fmt(get(p).gain.ci95, 3)}`))));
          }),
          h("tr", { style: "border-top:2px solid var(--line-2)" }, h("td", h("strong", "All profiles")), h("td"),
            ["adaptive", "sequential", "random"].map((p) => h("td.r.num", h("strong", `+${fmt(block.summary[p].gain, 3)}`)))))),
      h("p.small", { style: "margin-top:10px" },
        `Question repetition rate: adaptive ${fmt(block.summary.adaptive.exact_repeat_rate * 100, 2)}%, sequential ${fmt(block.summary.sequential.exact_repeat_rate * 100, 2)}%, random ${fmt(block.summary.random.exact_repeat_rate * 100, 2)}% of served questions were ones the student had seen. `,
        `After the last session the model's five weakest concepts overlap the truly weakest five by ${fmt(block.summary.adaptive.weakest5_last_session * 100, 0)}% (adaptive).`));
  }
  render("structured");
  return root;
}

function bankCard(stats) {
  const verified = Object.values(stats.questions_verified).reduce((a, b) => a + b, 0);
  const rejected = Object.values(stats.questions_rejected).reduce((a, b) => a + b, 0);
  const total = verified + rejected || 1;
  return h("div.card", h("h2", "Question bank verification"),
    h("p.muted.small", "Every generated question is checked for structure, arithmetic (numerical items are recomputed from their own formula) and by a blind solve from a second model. Only survivors are served."),
    h("div.bar", { style: "height:12px;margin:8px 0 4px" }, h("i", { style: `width:${(verified / total) * 100}%;background:var(--mastered)` }), h("i", { style: `width:${(rejected / total) * 100}%;background:var(--weak)` })),
    h("p.small", `${verified} verified, ${rejected} rejected (${fmt((rejected / total) * 100, 0)}% of well-formed drafts).`),
    h("table", h("thead", h("tr", h("th", "Rejected because"), h("th.r", "count"))),
      h("tbody", Object.entries(stats.questions_rejected).sort((a, b) => b[1] - a[1]).map(([reason, n]) => h("tr", h("td", reason), h("td.r.num", n))))),
    h("p.tiny", { style: "margin-top:8px" }, `Verified by type: ${Object.entries(stats.questions_verified).map(([k, v]) => `${v} ${k}`).join(", ")}. By difficulty: ${Object.entries(stats.questions_by_difficulty).map(([k, v]) => `level ${k}: ${v}`).join(", ")}.`));
}

export async function evidenceView() {
  const results = await api(coursePath("/evaluation"));
  const stats = state.overview.stats;
  const missing = ["ragas", "grounding", "retrieval", "simulation"].filter((k) => !results[k]);
  return h("div",
    h("div.head", h("div", h("h1", "Evidence"), h("p", "What was measured, on what, and how well it did. Every figure here is read from the evaluation's output files; the commands that produce them are in the README."))),
    missing.length ? h("div.note", { style: "margin-bottom:14px" }, `Not run yet: ${missing.join(", ")}. Run `, h("span.mono", "make eval"), ".") : null,
    h("div.grid.cols-2", results.ragas ? ragasCard(results.ragas) : null, results.grounding ? groundingCard(results.grounding) : null),
    results.retrieval ? h("section", retrievalCard(results.retrieval)) : null,
    results.simulation ? h("section", simulationCard(results.simulation)) : null,
    h("section", bankCard(stats)));
}
