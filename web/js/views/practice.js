// Practice: diagnostic, adaptive quiz and mock exam, with cited feedback and a report.
import { api, coursePath, fill, h, icon, pct, rich, state, studentPath } from "../core.js";
import { openCitation, sourceRow } from "../viewer.js";

const typeLabel = { mcq: "Multiple choice", short: "Short answer", numeric: "Numerical" };
const kinds = {
  diagnostic: { title: "Diagnostic", blurb: "Ten questions that walk the prerequisite map to place you across the whole course. Start here if you are new." },
  quiz: { title: "Adaptive quiz", blurb: "Questions chosen one at a time from your weakest ready concepts, at a difficulty you should get right about 85 % of the time. Feedback after each answer." },
  exam: { title: "Mock exam", blurb: "A fixed paper with even coverage of the scope and a spread of difficulty. Feedback at the end." },
};

function meter(before, after) {
  const up = after >= before;
  return h("span.shift",
    h("span.meter",
      h("i", { style: `width:${Math.max(before, after) * 100}%;background:${up ? "var(--mastered)" : "var(--weak)"};opacity:.35` }),
      h("i", { style: `width:${Math.min(before, after) * 100}%;background:var(--ink)` })),
    h("span.num", `${pct(before)} → ${pct(after)}`));
}

function feedbackCard(fb) {
  const cls = fb.score >= 0.99 ? "right" : fb.score > 0 ? "half" : "wrong";
  const title = fb.score >= 0.99 ? "Correct" : fb.score > 0 ? "Partly correct" : "Not correct";
  return h(`div.fb.${cls}`,
    h("div", { style: "display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:6px;flex-wrap:wrap" },
      h("strong", title), h("span", h("span.tiny", `${fb.concept} · `), meter(fb.mastery_before, fb.mastery_after))),
    fb.score < 0.99 && fb.correct_answer ? h("div.small", { style: "margin-bottom:6px", html: `<strong>Answer:</strong> ${rich(fb.correct_answer)}` }) : null,
    fb.misconception ? h("div.misc", { html: `<strong>Likely misconception:</strong> ${rich(fb.misconception)}` }) : null,
    fb.feedback && fb.graded_by === "model" ? h("div.small.muted", { style: "margin-bottom:6px", html: rich(fb.feedback) }) : null,
    h("div.why", { html: rich(fb.explanation) }),
    h("div.sources", fb.citations.map((c, i) => sourceRow(c, i + 1))));
}

function reportView(report, restart) {
  const weak = report.weak_topics;
  return h("div", { style: "max-width:900px" },
    h("div.head", h("div", h("h1", `${report.score.pct}%`), h("p", `${report.score.earned} of ${report.score.possible} on this ${report.kind}. Here is what it says about you.`)),
      h("div", { style: "display:flex;gap:8px" }, h("button.btn", { onclick: () => { location.hash = "#/progress"; } }, "See progress"), h("button.btn.primary", { onclick: restart }, "Practise again"))),
    h("div.grid.cols-2",
      h("div.card", h("h2", "Weak topics"),
        weak.length ? weak.map((w) => h("div", { style: "padding:8px 0;border-top:1px solid var(--line)" },
          h("div", { style: "display:flex;gap:8px;align-items:baseline;flex-wrap:wrap" }, h("strong", w.name), h("span.tiny", `· ${w.why}`),
            h("a.btn.sm", { href: `#/lessons/${w.concept_id}`, style: "margin-left:auto" }, icon("video"), "Lesson")),
          w.blocked_by ? h("div.small", { style: "color:var(--weak);margin:3px 0" }, `Root cause: “${w.blocked_by.name}” (${pct(w.blocked_by.mastery)}) comes first.`) : null,
          h("div.sources", { style: "border:0;padding:0" }, w.study.map((c) => sourceRow(c))))) : h("p.muted", "None in this sitting.")),
      h("div.card", h("h2", "Likely misconceptions"),
        report.misconceptions.length ? report.misconceptions.map((m) => h("div", { style: "padding:8px 0;border-top:1px solid var(--line)" },
          h("div.misc", { style: "margin:0 0 4px", html: rich(m.label) }),
          h("div.tiny", `${m.concept} · seen ${m.count}×`))) : h("p.muted", "No recognisable misconception behind the wrong answers."),
        h("h2", { style: "margin-top:16px" }, "Next steps"),
        h("ol", { style: "margin:0;padding-left:18px" }, report.next_steps.map((s) => h("li", { style: "margin-bottom:4px" }, s))))),
    h("section", h("div.card", h("h2", "By concept"),
      h("table", h("thead", h("tr", h("th", "Concept"), h("th.r", "Score"), h("th", "Mastery before → after"), h("th", "Level"))),
        h("tbody", report.by_concept.map((c) => h("tr",
          h("td", c.name), h("td.r.num", `${c.earned}/${c.asked}`), h("td", meter(c.mastery_before, c.mastery_after)),
          h("td", h(`span.chip.${c.level}`, c.level)))))))),
    h("section", h("div.section-title", h("h2", "Every question, with its source")),
      report.review.map((r, i) => h("div.card", { style: "margin-bottom:10px" },
        h("div.q-meta", h("span.chip", `${i + 1}`), h("span.chip", typeLabel[r.type]), h("span.chip", `difficulty ${r.difficulty}`)),
        h("div", { style: "font-family:var(--serif);font-size:16px;margin-bottom:6px", html: rich(r.stem) }),
        h("div.small.muted", "Your answer: ", String(r.response ?? "—")),
        feedbackCard(r.feedback)))));
}

export async function practiceView() {
  const root = h("div");
  const snapshot = (await api(studentPath())).concepts;
  const byId = Object.fromEntries(snapshot.map((c) => [c.concept_id, c]));
  const fresh = snapshot.every((c) => c.n_obs === 0);

  function home() {
    const chosen = new Set();
    let types = new Set(["mcq", "short", "numeric"]);
    const picker = h("div.pick", state.overview.concepts.map((c) => {
      const button = h("button", { onclick: () => {
        chosen.has(c.id) ? chosen.delete(c.id) : chosen.add(c.id);
        button.classList.toggle("on");
      } }, h(`span.dot.${byId[c.id]?.level || "unknown"}`), c.name);
      return button;
    }));
    const typePick = h("div.pick", Object.entries(typeLabel).map(([id, label]) => {
      const button = h("button.on", { onclick: () => {
        types.has(id) ? types.delete(id) : types.add(id);
        button.classList.toggle("on");
      } }, label);
      return button;
    }));
    const start = (kind) => begin(kind, { concept_ids: chosen.size ? [...chosen] : null, types: kind === "diagnostic" ? null : [...types] });
    fill(root,
      h("div.head", h("div", h("h1", "Practice"), h("p", "Every question is generated from your course material, checked by a second model and by arithmetic, and never repeated."))),
      fresh ? h("div.note", { style: "margin-bottom:14px" }, `No history for ${state.student.name} yet. The diagnostic takes about five minutes and tells the tutor where to start.`) : null,
      h("div.grid.cols-3", Object.entries(kinds).map(([kind, info]) => h("div.card",
        h("h2", info.title), h("p.muted.small", info.blurb),
        h(`button.btn${(kind === "diagnostic") === fresh ? ".primary" : ""}`, { onclick: () => start(kind) }, `Start ${info.title.toLowerCase()}`, icon("arrow"))))),
      h("section", h("div.card",
        h("h2", "Scope"), h("p.muted.small", "Pick concepts for a quiz or exam, or leave empty to cover everything. Dots show your current level."), picker,
        h("h3", { style: "margin:14px 0 8px" }, "Question types"), typePick)));
  }

  async function begin(kind, body) {
    root.replaceChildren(h("div.empty", "Choosing your first question…"));
    try {
      const started = await api(studentPath("/assessments"), { kind, ...body });
      show(started.assessment_id, kind, started.question);
    } catch (error) {
      root.replaceChildren(h("div.empty", h("h2", "Could not start"), h("p", error.message), h("button.btn", { onclick: home }, "Back")));
    }
  }

  function show(assessmentId, kind, question) {
    let response = null;
    const concept = state.overview.concepts.find((c) => c.id === question.concept_id);
    const answerArea = h("div");
    const submit = h("button.btn.primary", { disabled: true, onclick: () => send() }, "Submit");
    const after = h("div");

    if (question.type === "mcq") {
      answerArea.append(...question.options.map((text, index) => {
        const button = h("button.opt", { onclick: () => {
          response = index;
          answerArea.querySelectorAll(".opt").forEach((o) => { o.style.borderColor = ""; o.style.boxShadow = ""; });
          button.style.borderColor = "var(--ink)";
          button.style.boxShadow = "inset 0 0 0 1px var(--ink)";
          submit.disabled = false;
        } }, h("span.k", "ABCD"[index]), h("span", { html: rich(text) }));
        return button;
      }));
    } else {
      const input = question.type === "numeric"
        ? h("input.field", { type: "text", inputmode: "decimal", placeholder: "Your answer", style: "width:200px", oninput: (e) => { response = e.target.value; submit.disabled = !response.trim(); } })
        : h("textarea.field", { rows: 3, placeholder: "Answer in a sentence or two", style: "width:100%", oninput: (e) => { response = e.target.value; submit.disabled = !response.trim(); } });
      answerArea.append(h("div", { style: "display:flex;gap:10px;align-items:center" }, input, question.unit ? h("span.muted", { html: rich(question.unit.includes("\\") ? `$${question.unit}$` : question.unit) }) : null));
      input.addEventListener("keydown", (e) => { if (e.key === "Enter" && question.type === "numeric" && !submit.disabled) send(); });
      queueMicrotask(() => input.focus());
    }

    async function send() {
      submit.disabled = true;
      submit.textContent = "Checking…";
      const result = await api(coursePath(`/assessments/${assessmentId}/answers`), { question_id: question.id, response });
      answerArea.querySelectorAll("button, input, textarea").forEach((el) => { el.disabled = true; });
      const next = () => (result.done ? root.replaceChildren(reportView(result.report, home)) : show(assessmentId, kind, result.next));
      if (kind === "exam") return next();
      const fb = result.feedback;
      if (question.type === "mcq") {
        answerArea.querySelectorAll(".opt").forEach((o, i) => {
          if (i === fb.correct_option) o.classList.add("right");
          else if (i === response) o.classList.add("wrong");
        });
      }
      submit.remove();
      after.append(feedbackCard(fb), h("div", { style: "margin-top:14px" },
        h("button.btn.primary", { onclick: next }, result.done ? "See report" : "Next question", icon("arrow"))));
      if (fb.citations.length) openCitation(fb.citations[0]);
    }

    root.replaceChildren(
      h("div.progress", h("i", { style: `width:${((question.position - 1) / question.of) * 100}%` })),
      h("div.q-card",
        h("div.q-meta", h("span.tiny", `${kinds[kind].title} · question ${question.position} of ${question.of}`),
          h("span.chip", concept ? concept.name : question.concept_id), h("span.chip", typeLabel[question.type]), h("span.chip", `difficulty ${question.difficulty}`)),
        h("div.q-stem", { html: rich(question.stem) }), answerArea,
        h("div", { style: "margin-top:12px" }, submit), after));
  }

  home();
  return root;
}
