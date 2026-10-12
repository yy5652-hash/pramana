// Tutor: a conversation where every sentence of an answer is tied to a source you can open.
import { api, h, icon, pct, rich, speak, state, studentPath, toast } from "../core.js";
import { openCitation, sourceRow } from "../viewer.js";

const starters = [
  "What does Newton's second law say, and what are its units?",
  "How do I find the acceleration from a velocity–time graph?",
  "Explain static friction with the diagram from the slides.",
  "What is the work–energy theorem?",
  "How does a transformer neural network work?",
];

const verdictLabel = {
  covered: "Answered from your course material",
  partial: "Partly covered by your course material",
  not_covered: "Not in your course material",
};

function segmentHtml(segment, citations) {
  const marks = segment.citations.map((n) => `<button class="cite" data-n="${n}" title="${(citations.find((c) => c.n === n) || {}).label || ""}">${n}</button>`).join("");
  return `${rich(segment.text)} ${marks}`;
}

function tutorMessage(reply, language) {
  const el = h("div.msg.tutor");
  if (verdictLabel[reply.coverage]) el.append(h(`div.verdict.${reply.coverage}`, verdictLabel[reply.coverage]));

  if (reply.refused) {
    el.append(h("div.refusal",
      h("div", { html: rich(reply.missing || "Your course material does not cover this, so I will not answer it from memory.") }),
      reply.related.length ? h("div.small.muted", { style: "margin-top:8px" }, "The closest material I do have:") : null,
      reply.related.length ? h("div.sources", { style: "border:0;padding:0;margin-top:4px" }, reply.related.map((c) => sourceRow(c))) : null));
  } else {
    const body = h("div.body", { html: reply.segments.map((s) => `<p>${segmentHtml(s, reply.citations)}</p>`).join("") });
    body.querySelectorAll(".cite").forEach((button) => {
      const c = reply.citations.find((x) => String(x.n) === button.dataset.n);
      button.dataset.unit = c.unit_id;
      button.addEventListener("click", () => openCitation(c, button));
    });
    el.append(body);
    if (reply.coverage === "partial" && reply.missing) el.append(h("div.note", { style: "margin-top:8px", html: `<strong>Not covered:</strong> ${rich(reply.missing)}` }));
    if (!reply.citations.length && reply.related && reply.related.length) {
      el.append(h("div.sources", reply.related.map((c) => sourceRow(c))));
    }
  }
  if (reply.outside) {
    el.append(h("div.outside", h("div.label", "Not from your course material"), h("div", { html: rich(reply.outside) })));
  }
  if (reply.citations.length) {
    el.append(h("div.sources", reply.citations.map((c) => sourceRow(c, c.n))));
  }
  if (reply.check) {
    el.append(h("div.check", h("div.label", "Check your understanding"), h("div", { html: rich(reply.check.question) }),
      h("div.tiny", { style: "margin-top:4px" }, "Answer in the box below. Your answer updates your mastery estimate.")));
  }
  if (reply.learner_updates && reply.learner_updates.length) {
    el.append(h("div.updates", reply.learner_updates.map((u) =>
      h("span.update", { title: u.why }, h("b", u.name), ` ${pct(u.before)} → ${pct(u.after)} · ${u.why}`))));
  }
  const text = reply.segments.map((s) => s.text).join(" ");
  if (text) {
    el.append(h("div", { style: "margin-top:6px" },
      h("button.btn.ghost.sm", { onclick: () => speak(text, language), title: "Read this answer aloud" }, icon("speaker"), "Listen")));
  }
  return el;
}

export async function tutorView() {
  const thread = h("div.thread");
  const input = h("textarea", { placeholder: "Ask about your course…", rows: 1, "aria-label": "Message" });
  let busy = false;

  const history = await api(studentPath("/messages"));
  for (const message of history.slice(-12)) {
    if (message.role === "student") thread.append(h("div.msg.student", message.content));
    else if (message.meta.reply) thread.append(tutorMessage(message.meta.reply, message.meta.reply.language || "en"));
  }

  async function send(text) {
    const message = (text ?? input.value).trim();
    if (!message || busy) return;
    busy = true;
    input.value = "";
    intro.remove();
    thread.append(h("div.msg.student", message));
    const waiting = h("div.msg.tutor", h("span.thinking", "Reading your course material"));
    thread.append(waiting);
    thread.scrollTop = thread.scrollHeight;
    try {
      const reply = await api(studentPath("/chat"), { message, language: state.language, allow_outside: state.allowOutside });
      const el = tutorMessage(reply, state.language);
      waiting.replaceWith(el);
      el.scrollIntoView({ block: "start", behavior: "smooth" });
      if (reply.citations.length) openCitation(reply.citations[0]);
    } catch (error) {
      waiting.replaceWith(h("div.msg.tutor", h("div.refusal", `The tutor could not answer: ${error.message}`)));
    }
    busy = false;
    input.focus();
  }

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send(); }
  });

  const languages = [["en", "English"], ["hi", "हिंदी"], ["hinglish", "Hinglish"]];
  const language = h("div.seg", { role: "group", "aria-label": "Answer language" }, languages.map(([id, label]) =>
    h(`button${state.language === id ? ".on" : ""}`, { onclick: (event) => {
      state.language = id;
      localStorage.setItem("pramana.language", id);
      language.querySelectorAll("button").forEach((b) => b.classList.remove("on"));
      event.target.classList.add("on");
    } }, label)));
  const outside = h("label.toggle", { title: "When the material does not cover a question, also show an answer from general knowledge, clearly labelled." },
    h("input", { type: "checkbox", checked: state.allowOutside, onchange: (event) => {
      state.allowOutside = event.target.checked;
      localStorage.setItem("pramana.outside", state.allowOutside ? "1" : "0");
    } }), "Allow outside knowledge (labelled)");

  // Voice input, where the browser supports it.
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const mic = Recognition ? h("button.btn", { title: "Speak your question", "aria-label": "Speak your question", onclick: () => {
    const recognition = new Recognition();
    recognition.lang = state.language === "en" ? "en-IN" : "hi-IN";
    recognition.onresult = (event) => { input.value = event.results[0][0].transcript; send(); };
    recognition.onerror = (event) => toast(`Voice input: ${event.error}`);
    recognition.start();
    toast("Listening…");
  } }, icon("mic")) : null;

  const intro = h("div", { style: "margin:auto 0" },
    h("h1", `Ask ${state.course.title}`),
    h("p.muted", { style: "max-width:60ch;margin-top:8px" },
      "Answers are built only from your textbook, slides and lectures. Each sentence carries a number; click it to open the exact page, slide or second it came from. If the material does not cover a question, the tutor says so."),
    h("div.starters", starters.map((text) => h("button.btn", { onclick: () => send(text) }, text))));
  if (!history.length) thread.append(intro);

  queueMicrotask(() => { thread.scrollTop = thread.scrollHeight; input.focus(); });
  return h("div.tutor-view",
    h("div.tutor-bar", h("h2", "Tutor"), h("span.tiny", `as ${state.student.name}`), h("span", { style: "flex:1" }), language, outside),
    thread,
    h("div.composer", input, mic, h("button.btn.primary", { onclick: () => send(), "aria-label": "Send" }, icon("send"), "Ask")));
}
