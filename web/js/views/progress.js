// Progress: the learner model made visible. Mastery per concept, the evidence behind each
// number, a study schedule built from weak topics and forgetting curves, and cited flashcards.
import { api, fill, h, icon, pct, rich, speak, state, studentPath } from "../core.js";
import { sourceRow } from "../viewer.js";

const sourceLabel = { quiz: "quiz answer", diagnostic: "diagnostic answer", chat: "conversation", inferred: "inferred from the course map" };

function ago(ts) {
  const minutes = (Date.now() / 1000 - ts) / 60;
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${Math.round(minutes)} min ago`;
  if (minutes < 1440) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} d ago`;
}

export async function progressView() {
  const data = await api(studentPath());
  const concepts = data.concepts;
  const byId = Object.fromEntries(concepts.map((c) => [c.concept_id, c]));
  const assessed = concepts.filter((c) => c.n_obs > 0);
  const counts = { mastered: 0, developing: 0, weak: 0, unknown: 0 };
  concepts.forEach((c) => { counts[c.level] += 1; });
  const repeats = data.attempts.n - data.attempts.distinct_questions;

  const mastery = h("div.card", h("h2", "Mastery by concept"),
    h("div.legend", { style: "margin-bottom:10px" },
      ["mastered", "developing", "weak", "unknown"].map((l) => h("span", h(`i.dot.${l}`), `${l} (${counts[l]})`)),
      h("span", h("i", { style: "border-right:2px dashed var(--ink-3);width:2px;height:10px;border-radius:0" }), "before forgetting")),
    state.overview.topics.map((topic) => h("div", { style: "margin-top:10px" },
      h("div.tiny", { style: "text-transform:uppercase;letter-spacing:.08em;margin-bottom:2px" }, topic.title),
      concepts.filter((c) => c.topic_id === topic.id).map((c) => h("div.concept-row",
        h("div", { title: c.blocked_by ? `Rests on “${byId[c.blocked_by].name}”, which is not secure` : "" }, c.name,
          c.blocked_by ? h("span.tiny", { style: "color:var(--weak)" }, ` ← ${byId[c.blocked_by].name}`) : null),
        h("div.track", h("i", { style: `width:${c.mastery * 100}%;background:var(--${c.level})` }),
          c.stored - c.mastery > 0.02 ? h("i.ghost", { style: `width:${c.stored * 100}%` }) : null),
        h("div.num", { style: "text-align:right" }, c.n_obs ? pct(c.mastery) : "—"),
        h("div.tiny", c.n_obs ? `${c.n_obs} obs` + (c.review_in_days !== null && c.level === "mastered" ? ` · review in ${Math.max(0, Math.round(c.review_in_days))} d` : "") : "not assessed"))))));

  const timeline = h("div.card", h("h2", "Why the numbers are what they are"),
    h("p.muted.small", "Every update to the model, newest first: what happened, and how far it moved the estimate."),
    data.evidence.length ? h("div.timeline", data.evidence.slice(0, 14).map((e) => {
      const up = e.p_after >= e.p_before;
      const note = e.detail.misconception || e.detail.note || (e.detail.from ? `because of “${byId[e.detail.from]?.name || e.detail.from}”` : "");
      return h("div.ev",
        h("span.tiny", ago(e.ts)),
        h("span", h("strong", byId[e.concept_id]?.name || e.concept_id), h("span.muted", ` · ${sourceLabel[e.source] || e.source}`),
          e.source !== "inferred" ? h("span.muted", e.correct >= 0.99 ? " · correct" : e.correct > 0 ? " · partly" : " · incorrect") : null,
          note ? h("div.tiny", note) : null),
        h("span.num", { style: `color:${up ? "var(--mastered)" : "var(--weak)"};text-align:right` }, `${pct(e.p_before)} → ${pct(e.p_after)}`));
    })) : h("p.muted", "No evidence yet. Take the diagnostic in Practice."));

  // ---- schedule ----
  const scheduleBody = h("div", h("p.muted", "Set your exam date and daily time, then build a plan."));
  const days = h("input.field", { type: "number", value: 10, min: 2, max: 60, style: "width:72px" });
  const minutes = h("input.field", { type: "number", value: 45, min: 15, max: 240, step: 5, style: "width:72px" });
  async function buildSchedule() {
    scheduleBody.replaceChildren(h("p.muted", "Planning…"));
    const plan = await api(studentPath(`/schedule?days=${days.value}&minutes=${minutes.value}`));
    const slipping = plan.without_review.filter((c) => c.today - c.on_exam_day > 0.05).sort((a, b) => (b.today - b.on_exam_day) - (a.today - a.on_exam_day)).slice(0, 4);
    fill(scheduleBody,
      slipping.length ? h("div.note", { style: "margin-bottom:10px" }, "Without review, the forgetting curve predicts by exam day: ",
        slipping.map((c, i) => h("span", i ? "; " : "", h("strong", c.name), ` ${pct(c.today)} → ${pct(c.on_exam_day)}`)), ".") : null,
      plan.days.map((day) => h("div.day",
        h("div", h("strong", `Day ${day.day}`), h("div.tiny", day.date), h("div.tiny", `${day.minutes} min`)),
        h("div", day.items.map((item) => h("div", { style: "margin-bottom:6px" },
          h("div.task", h(`span.k.${item.kind}`, item.kind), h("strong", item.name), h("span.tiny", `${item.minutes} min · ${item.why}`)),
          item.links.length ? h("div", { style: "margin-left:4px" }, item.links.map((c) => sourceRow(c))) : null))))),
      plan.unscheduled.length ? h("div.note", { style: "margin-top:10px" }, `Did not fit before the exam: ${plan.unscheduled.map((u) => `${u.name} (${u.kind})`).join(", ")}. Add days or minutes.`) : null);
  }
  const scheduleCard = h("div.card", h("div.section-title", h("h2", "Study schedule"),
    h("span", { style: "margin-left:auto;display:flex;gap:8px;align-items:center" }, h("span.small.muted", "Exam in"), days, h("span.small.muted", "days,"), minutes, h("span.small.muted", "min/day"),
      h("button.btn.sm.primary", { onclick: buildSchedule }, "Build plan"))), scheduleBody);

  // ---- flashcards ----
  const cardsBody = h("div", h("p.muted", "Cards are written from the sources for your weakest concepts, each with its citation."));
  async function loadCards() {
    cardsBody.replaceChildren(h("p.muted", "Writing cards from your material…"));
    try {
      const cards = await api(studentPath("/flashcards"));
      cardsBody.replaceChildren(h("div.cards", cards.map((card) => {
        let flipped = false;
        const face = h("div.f", { html: rich(card.front) });
        const foot = h("div.tiny", card.concept);
        const el = h("button.flash", { onclick: () => {
          flipped = !flipped;
          el.classList.toggle("flipped", flipped);
          face.innerHTML = rich(flipped ? card.back : card.front);
          foot.replaceChildren(flipped && card.citations[0] ? `${card.citations[0].source_title} · ${card.citations[0].place}` : card.concept);
        } }, h("div.tiny", { style: "text-transform:uppercase;letter-spacing:.08em" }, "flashcard"), face, h("span", { style: "flex:1" }), foot);
        return el;
      })), h("div", { style: "margin-top:10px" }, h("button.btn.sm", { onclick: () => speak(cards.map((c) => `${c.front}. ${c.back}`).join(". ")) }, icon("speaker"), "Play as audio brief")));
    } catch (error) {
      cardsBody.replaceChildren(h("p.muted", `Could not write cards: ${error.message}`));
    }
  }
  const cardsCard = h("div.card", h("div.section-title", h("h2", "Revision cards for weak topics"),
    h("button.btn.sm.primary", { style: "margin-left:auto", onclick: loadCards }, "Make cards")), cardsBody);

  return h("div",
    h("div.head", h("div", h("h1", `${state.student.name}'s progress`), h("p", "A Bayesian knowledge-tracing model with forgetting and prerequisite structure. It updates after every quiz answer and every conversation."))),
    h("div.grid.cols-4",
      h("div.card.stat", h("div.n", `${assessed.length}/${concepts.length}`), h("div.l", "concepts assessed")),
      h("div.card.stat", h("div.n", assessed.length ? pct(assessed.reduce((a, c) => a + c.mastery, 0) / assessed.length) : "—"), h("div.l", "mean mastery (assessed)")),
      h("div.card.stat", h("div.n", data.attempts.n), h("div.l", "questions answered")),
      h("div.card.stat", h("div.n", repeats), h("div.l", "repeated questions"), h("div.s", "the selector never re-serves an item"))),
    h("section", h("div.grid.cols-2", mastery, timeline)),
    h("section", scheduleCard),
    h("section", cardsCard));
}
