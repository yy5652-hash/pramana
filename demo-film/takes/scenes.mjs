// The takes of the film. Each scene drives the real app like a person would; nothing is staged
// beyond choosing which student is logged in and, in practice scenes, deciding in advance
// whether to answer rightly or wrongly (the answer key is read from the course database).
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// The product repository: this folder lives inside it as demo-film/takes, or beside it while the film is being made.
const HERE = dirname(fileURLToPath(import.meta.url));
const PRAMANA = [join(HERE, "../.."), join(HERE, "../../pramana")].find((dir) => existsSync(join(dir, "pramana", "__init__.py")));
const COURSE = "mechanics";

/** Correct option index (MCQ) or value (numeric) of a question, read from the knowledge base. */
function key(questionId) {
  const code = `import json,sqlite3;r=sqlite3.connect("data/kb/${COURSE}/kb.sqlite").execute("select type,answer from questions where id=?",("${questionId}",)).fetchone();a=json.loads(r[1]);print(json.dumps({"type":r[0],"option":a.get("option"),"value":a.get("value")}))`;
  const out = spawnSync(`${PRAMANA}/.venv/bin/python`, ["-c", code], { cwd: PRAMANA, encoding: "utf8" });
  return JSON.parse(out.stdout);
}

async function student(take, name) {
  const created = await take.api(`/courses/${COURSE}/students`, { name });
  return created.id;
}

const login = (id, extra = "") => `localStorage.setItem("pramana.student.${COURSE}", "${id}"); localStorage.setItem("pramana.language", "en"); localStorage.setItem("pramana.outside", "0"); ${extra}`;

/** Answer a whole assessment through the API, right or wrong per `plan(question, index)`. */
async function sit(take, studentId, kind, plan, n) {
  let state = await take.api(`/courses/${COURSE}/students/${studentId}/assessments`, { kind, n });
  let question = state.question;
  let index = 0;
  while (question) {
    const answer = key(question.id);
    const right = plan(question, index);
    const response = answer.type === "mcq" ? (right ? answer.option : (answer.option + 1) % 4) : (right ? String(answer.value) : String(-answer.value || 1));
    const result = await take.api(`/courses/${COURSE}/assessments/${state.assessment_id}/answers`, { question_id: question.id, response: answer.type === "short" ? "I am not sure." : response });
    question = result.next;
    index += 1;
  }
}

async function ask(take, text) {
  await take.click(`document.querySelector(".composer textarea")`);
  await take.type(text);
  take.mark("typed");
  await take.wait(450);
  const before = await take.run(`document.querySelectorAll(".msg.tutor").length`);
  await take.click(`document.querySelector(".composer .btn.primary")`);
  take.mark("asked");
  await take.until(`document.querySelectorAll(".msg.tutor").length > ${before} && !document.querySelector(".thinking")`, "the tutor's answer", 90000);
  take.mark("answered");
}

export const scenes = {
  // The heart of the film: a question, an answer whose every sentence carries a number, and
  // the numbers opening the textbook page and the second of the lecture.
  ask: async (take) => {
    const id = await student(take, "Asha");
    await take.goto("#/tutor", login(id));
    await take.start();
    await take.wait(1400);
    await ask(take, "How is Newton's second law written in terms of momentum?");
    await take.wait(3200);
    const cited = await take.run(`[...document.querySelectorAll(".msg.tutor:last-child .sources .source-row")].map((r) => r.dataset.unit)`);
    const page = cited.findIndex((u) => u.startsWith("textbook"));
    const video = cited.findIndex((u) => u.startsWith("v-"));
    const row = (i) => `document.querySelectorAll(".msg.tutor:last-child .sources .source-row")[${i}]`;
    if (page >= 0) {
      await take.click(row(page));
      take.mark("page-open");
      await take.wait(4200);
    }
    if (video >= 0) {
      await take.click(row(video));
      take.mark("video-open");
      await take.until(`document.querySelector("#viewer video") && document.querySelector("#viewer video").readyState >= 2`, "the lecture video", 20000);
      await take.wait(1500);
      await take.click(`document.querySelector("#viewer .btn.sm")`);
      take.mark("video-play");
      await take.wait(9000);
      await take.run(`document.querySelector("#viewer video").pause()`);
    }
    await take.wait(800);
    return { cited };
  },

  // What it will not do: answer from memory.
  refuse: async (take) => {
    const id = await student(take, "Asha");
    await take.goto("#/tutor", login(id));
    await take.start();
    await take.wait(1000);
    await ask(take, "How does a transformer neural network use self-attention?");
    await take.wait(3000);
    await ask(take, "What is the moment of inertia of a solid sphere?");
    await take.wait(4200);
  },

  // A wrong answer, read as a misconception and traced to its source.
  practice: async (take) => {
    const id = await student(take, "Asha");
    await take.goto("#/practice", login(id));
    await take.start();
    await take.wait(1500);
    await take.click(`[...document.querySelectorAll(".card .btn")].find((b) => b.textContent.includes("diagnostic"))`);
    take.mark("started");
    for (const right of [true, false, false]) {
      await take.until(`document.querySelector(".q-stem") && !document.querySelector(".fb")`, "a question");
      await take.wait(2400);
      const question = await take.run(`(() => { const o = document.querySelectorAll(".opt"); return { n: o.length }; })()`);
      const current = await take.api(`/courses/${COURSE}/students/${id}`);
      const open = await take.api(`/courses/${COURSE}/assessments/${current.assessments[0].id}`);
      const answer = key(open.question_ids[open.question_ids.length - 1]);
      if (question.n) {
        const choice = right ? answer.option : (answer.option + 2) % 4;
        await take.click(`document.querySelectorAll(".opt")[${choice}]`);
      } else {
        await take.click(`document.querySelector(".q-card input, .q-card textarea")`);
        // The wrong number is a common slip the grader can name: a factor of two (a dropped or doubled ½).
        await take.type(right ? String(answer.value) : String(Number((answer.value * 2).toPrecision(3))), 120);
      }
      await take.wait(700);
      await take.click(`[...document.querySelectorAll(".q-card .btn.primary")].find((b) => b.textContent.includes("Submit"))`);
      await take.until(`document.querySelector(".fb")`, "feedback");
      const misconception = await take.run(`document.querySelector(".fb .misc")?.textContent || ""`);
      take.mark(right ? "feedback-right" : "feedback-wrong", right ? {} : { misconception });
      // Park the pointer in the margin so it does not sit on the verdict while it is read.
      await take.moveTo(await take.run(`(() => { const r = document.querySelector(".fb").getBoundingClientRect(); return { x: r.left - 36, y: r.top + 170 }; })()`), 520);
      if (right) {
        await take.wait(2600);
      } else {
        await take.wait(1100);            // the viewer has opened and scrolled to the cited passage
        await take.markRect("question", `document.querySelector(".q-stem")`);
        await take.markRect("verdict", `document.querySelector(".fb")`);
        await take.markRect("meter", `document.querySelector(".fb .shift")`, { text: await take.run(`document.querySelector(".fb .shift .num").textContent`) });
        await take.markRect("source", `document.querySelector("#viewer .hl") || document.querySelector("#viewer .slide img") || document.querySelector("#viewer video")`);
        await take.wait(4800);
      }
      await take.click(`[...document.querySelectorAll(".q-card .btn.primary")].find((b) => b.textContent.includes("Next"))`);
    }
    await take.wait(1200);
  },

  // A lesson: the app cuts a short film on this student's weakest concept from the course itself.
  lessons: async (take) => {
    const id = await student(take, "Asha");
    // A student who is fine everywhere except Newton's second law: the learner model then
    // recommends that lesson by itself, and the lectures hold the lecturer stating the law.
    await sit(take, id, "diagnostic", (q) => q.concept_id !== "newtons-second-law", 10);
    await take.goto("#/lessons", login(id));
    await take.start();
    await take.wait(2400);
    const button = `[...document.querySelectorAll(".btn.primary")].find((b) => b.textContent.includes("Cut this lesson"))`;
    await take.markRect("button", `(${button}).closest(".card")`);
    await take.click(button);
    take.mark("cut");
    await take.until(`document.querySelector(".lesson-video")`, "the finished lesson", 420000);
    take.mark("made");
    await take.run(`document.querySelector(".lesson-video").scrollIntoView({ block: "start", behavior: "smooth" })`);
    await take.until(`document.querySelector(".lesson-video").readyState >= 2`, "the film to load", 30000);
    await take.wait(1100);
    await take.markRect("lesson", `document.querySelector(".lesson")`);
    await take.click(`document.querySelector(".scene-head")`);
    take.mark("play");
    await take.wait(9500);
    await take.run(`document.querySelector(".lesson-video").pause()`);
    const board = (await take.api(`/courses/${COURSE}/students/${id}/lessons`)).lessons[0];
    await take.save(board.video, "lessons/demo.mp4");
    return { student: id, lesson: { concept: board.concept, seconds: board.seconds, why: board.why, model: board.model,
      scenes: board.scenes.map((scene) => ({ kind: scene.kind, at: scene.at, seconds: scene.seconds })) } };
  },

  // The learner model, visible: mastery, the evidence behind it, and a plan.
  progress: async (take) => {
    const id = await student(take, "Asha");
    // A believable history: strong on kinematics, shaky from Newton's second law on.
    await sit(take, id, "diagnostic", (q, i) => i < 4 || i === 6, 10);
    await sit(take, id, "quiz", (q, i) => i % 3 !== 1, 8);
    await take.goto("#/progress", login(id));
    await take.start();
    await take.wait(4500);
    await take.scroll(`document.getElementById("view")`, 430, 1600);
    await take.wait(2600);
    // Bring the schedule card up before reaching for its button.
    const top = await take.run(`(() => { const view = document.getElementById("view"); const card = [...document.querySelectorAll(".card")].find((c) => c.textContent.includes("Study schedule")); return Math.round(view.scrollTop + card.getBoundingClientRect().top - 90); })()`);
    await take.scroll(`document.getElementById("view")`, top, 1500);
    await take.wait(700);
    await take.click(`[...document.querySelectorAll(".btn")].find((b) => b.textContent.includes("Build plan"))`);
    take.mark("plan");
    await take.until(`document.querySelector(".day")`, "the study plan");
    await take.wait(3200);
    await take.scroll(`document.getElementById("view")`, top + 420, 1800);
    await take.wait(3500);
    return { student: id };
  },

  // The course map, coloured by the same student's mastery.
  map: async (take) => {
    const id = await student(take, "Asha");
    await sit(take, id, "diagnostic", (q, i) => i < 4 || i === 6, 10);
    await sit(take, id, "quiz", (q, i) => i % 3 !== 1, 8);
    await take.goto("#/map", login(id));
    await take.start();
    await take.wait(3500);
    await take.click(`[...document.querySelectorAll(".node")].find((n) => n.textContent.includes("Second Law"))`);
    take.mark("node");
    await take.wait(2200);
    await take.scroll(`document.getElementById("view")`, 500, 1500);
    await take.wait(4000);
  },

  // How a page was read: the figure, outlined, next to what vision wrote down about it.
  library: async (take) => {
    const id = await student(take, "Asha");
    await take.goto("#/library", login(id));
    await take.start();
    await take.wait(3500);
    await take.click(`document.querySelector(".src")`);
    await take.until(`document.querySelectorAll(".unit").length > 50`, "the unit list");
    await take.wait(1200);
    await take.run(`[...document.querySelectorAll(".unit")].find((u) => u.textContent.includes("Figure 5.10")).scrollIntoView({ block: "center", behavior: "smooth" })`);
    await take.wait(1500);
    await take.click(`[...document.querySelectorAll(".unit")].find((u) => u.textContent.includes("Figure 5.10"))`);
    take.mark("figure");
    await take.wait(5500);
  },

  // The evaluation page, top to bottom.
  evidence: async (take) => {
    const id = await student(take, "Asha");
    await take.goto("#/evidence", login(id));
    await take.start();
    await take.wait(3500);
    for (const top of [520, 1080, 1700]) {
      await take.scroll(`document.getElementById("view")`, top, 1600);
      await take.wait(3200);
    }
  },
};
