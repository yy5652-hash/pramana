// Lessons: a short narrated film on one concept, cut from the course's own pages, slides and
// lectures. Beside the player, every scene is listed with the source it shows; clicking the
// source opens it at the page, slide or second, exactly as a citation in the tutor does.
import { api, fill, h, icon, pct, rich, state, studentPath } from "../core.js";
import { sourceRow } from "../viewer.js";

const clock = (seconds) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
const shows = { read: "the textbook", figure: "a figure", slide: "a slide", board: "the lecture", listen: "the lecturer, in their own words" };
const part = { problem: "the problem", strategy: "the strategy", solution: "the solution", significance: "what it means" };
// What a scene is, in the list beside the film.
const label = (scene) => scene.kind === "example" ? `worked example · ${part[scene.role] || scene.role}`
  : scene.kind === "mistake" ? (scene.own ? "your own answer in practice" : "a mistake to avoid")
  : shows[scene.kind] || scene.kind;
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export async function lessonsView() {
  const [data, student] = await Promise.all([api(studentPath("/lessons")), api(studentPath())]);
  const byId = Object.fromEntries(student.concepts.map((c) => [c.concept_id, c]));
  const stage = h("div");
  const earlier = h("div");
  // "#/lessons/<concept>" arrives with a concept already chosen (from the course map or a report).
  const asked = location.hash.split("/")[2];
  let chosen = byId[asked] ? asked : data.next.concept_id;

  function player(lesson) {
    const video = h("video.lesson-video", { src: lesson.video, controls: true, preload: "metadata", playsinline: true });
    const scenes = lesson.scenes.filter((scene) => scene.citation);
    const rows = scenes.map((scene) => {
      const head = h("button.scene-head", { onclick: () => { video.currentTime = scene.at + 0.05; video.play(); } },
        h("span.n", scene.n), h("span", label(scene)), h("span.tiny", clock(scene.at)));
      const said = scene.kind === "listen"
        ? h("div.said", h("em", `“${scene.focus}”`))
        : h("div.said", scene.narration);
      return h("div.scene", head, said, sourceRow(scene.citation, scene.n));
    });
    video.addEventListener("timeupdate", () => {
      scenes.forEach((scene, i) => rows[i].classList.toggle("on", video.currentTime >= scene.at && video.currentTime < scene.at + scene.seconds));
    });
    fill(stage, h("div.lesson",
      h("div",
        video,
        h("h2", { style: "margin:14px 0 4px" }, lesson.concept),
        h("p.muted.small", { style: "margin:0" }, `${clock(lesson.seconds)} · cut for ${lesson.student} because ${lesson.why}`,
          lesson.starts_from ? ` · opens with “${lesson.starts_from}”, which it rests on` : ""),
        h("div", { style: "margin-top:12px;display:flex;gap:8px;flex-wrap:wrap" },
          h("button.btn.primary", { onclick: () => { location.hash = "#/practice"; } }, "Check yourself in Practice", icon("arrow")),
          h("a.btn", { href: lesson.video, download: `${lesson.concept}.mp4` }, "Download the film"))),
      h("div.card",
        h("h2", "Every scene, and its source"),
        h("p.muted.small", { style: "margin:0 0 6px" }, "The film shows nothing but your own course. Open any source at the place the scene shows."),
        rows, ending(lesson, video))));
  }

  // What the lesson gathers at the end, and the question it leaves the student with.
  function ending(lesson, video) {
    const recap = lesson.scenes.find((scene) => scene.kind === "recap");
    const check = lesson.scenes.find((scene) => scene.kind === "check");
    const jump = (scene) => () => { video.currentTime = scene.at + 0.05; video.play(); };
    return [
      recap ? h("div.scene",
        h("button.scene-head", { onclick: jump(recap) }, h("span.n", "✓"), h("span", "to keep"), h("span.tiny", clock(recap.at))),
        h("ul.keep", recap.points.map((point) => h("li", h("span.n", point.n), h("span", point.text))))) : null,
      check ? h("div.scene",
        h("button.scene-head", { onclick: jump(check) }, h("span.n", "?"), h("span", "the question it ends on"), h("span.tiny", clock(check.at))),
        h("div.said", { html: rich(check.card.stem) }),
        check.card.options.length ? h("ol.options", check.card.options.map((option) => h("li", { html: rich(option) }))) : null,
        h("button.btn.sm", { style: "margin:6px 0 4px", onclick: () => { location.hash = "#/practice"; } }, "Answer it in Practice", icon("arrow"))) : null,
    ];
  }

  function listEarlier() {
    fill(earlier, data.lessons.length > 1 || (data.lessons.length && !stage.querySelector("video")) ? h("section", h("div.card", h("h2", "Your lessons"),
      data.lessons.map((lesson) => h("button.source-row", { onclick: () => { player(lesson); stage.scrollIntoView({ behavior: "smooth" }); } },
        h("span.n", icon("video")), h("span", h("div.t", lesson.concept), h("div.x", `${clock(lesson.seconds)} · ${new Date(lesson.created * 1000).toLocaleString()}`)), h("span"))))) : null);
  }

  async function make() {
    const bar = h("i", { style: "width:2%" });
    const step = h("p.muted", "Choosing sources and writing the narration…");
    fill(stage, h("div.card", h("h2", `Cutting a lesson on ${byId[chosen]?.name || "this concept"}`),
      h("div.progress", { style: "margin:14px 0 10px" }, bar), step,
      h("p.tiny", "About a minute. The narration is voiced and the film is cut on this machine; nothing is sent anywhere except the request that writes the script.")));
    try {
      let job = await api(studentPath("/lessons"), { concept_id: chosen });
      while (job.status === "running") {
        await wait(900);
        job = await api(`/jobs/${job.id}`);
        step.textContent = job.step === "cutting the film" ? `Cutting the film… ${pct(job.progress)}` : `${job.step[0].toUpperCase()}${job.step.slice(1)}…`;
        bar.style.width = `${job.step === "cutting the film" ? 30 + job.progress * 70 : 12}%`;
      }
      if (job.status !== "done") throw new Error(job.error || "the lesson could not be made");
      data.lessons.unshift(job.lesson);
      player(job.lesson);
      listEarlier();
    } catch (error) {
      fill(stage, h("div.card", h("h2", "No lesson this time"), h("p.muted", String(error.message || error)),
        h("p.tiny", "A lesson is only made when enough of its scenes can be tied to a source in your course.")));
    }
  }

  const picker = h("div.pick", state.overview.concepts.map((c) => {
    const button = h(`button${c.id === chosen ? ".on" : ""}`, { onclick: () => {
      chosen = c.id;
      picker.querySelectorAll("button").forEach((b) => b.classList.remove("on"));
      button.classList.add("on");
    } }, h(`span.dot.${byId[c.id]?.level || "unknown"}`), c.name);
    return button;
  }));

  if (data.lessons.length) player(data.lessons[0]);
  listEarlier();
  return h("div",
    h("div.head", h("div", h("h1", "Lessons"),
      h("p", "A narrated film of about two minutes on one concept, cut from your own textbook, slides and lectures: the idea, the rule, a worked example from the book, a mistake (your own, if you have made one in practice), what to keep, and one question. The narrator may only say what a source says, and every scene shows that source."))),
    !data.voice ? h("div.note", { style: "margin-bottom:14px" }, "The narrator's voice is not installed (pip install kokoro-onnx). Lessons will be cut with captions and the lecturer's own voice only.") : null,
    h("div.card",
      h("h2", "Your next lesson"),
      h("p", { style: "margin:0 0 10px" }, h("strong", data.next.name), h("span.muted", `, because ${data.next.why}.`)),
      h("p.muted.small", { style: "margin:0 0 8px" }, "Or pick another concept. Dots show your current level."), picker,
      h("div", { style: "margin-top:14px" }, h("button.btn.primary", { onclick: make }, icon("video"), "Cut this lesson"))),
    h("section", stage),
    earlier);
}
