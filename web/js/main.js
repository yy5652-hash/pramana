// App shell: loads the course, keeps the student picker, routes #/section to a view.
import { api, coursePath, h, icon, state, toast } from "./core.js";
import { closeViewer } from "./viewer.js";
import { libraryView } from "./views/library.js";
import { mapView } from "./views/map.js";
import { tutorView } from "./views/tutor.js";
import { lessonsView } from "./views/lessons.js";
import { practiceView } from "./views/practice.js";
import { progressView } from "./views/progress.js";
import { evidenceView } from "./views/evidence.js";

const sections = [
  { id: "tutor", label: "Tutor", icon: "chat", view: tutorView },
  { id: "lessons", label: "Lessons", icon: "video", view: lessonsView },
  { id: "practice", label: "Practice", icon: "quiz", view: practiceView },
  { id: "progress", label: "Progress", icon: "chart", view: progressView },
  { id: "map", label: "Course map", icon: "map", view: mapView },
  { id: "library", label: "Library", icon: "library", view: libraryView },
  { id: "evidence", label: "Evidence", icon: "proof", view: evidenceView },
];

function renderNav(active) {
  document.getElementById("nav").replaceChildren(...sections.map((s) =>
    h(`a${s.id === active ? ".on" : ""}`, { href: `#/${s.id}` }, icon(s.icon), s.label)));
}

async function loadStudents() {
  state.students = await api(coursePath("/students"));
  const saved = localStorage.getItem(`pramana.student.${state.course.id}`);
  state.student = state.students.find((s) => s.id === saved) || state.students[0] || null;
  if (!state.student) {
    state.student = await api(coursePath("/students"), { name: "Asha" });
    state.students = [state.student];
  }
  renderWho();
}

function renderWho() {
  const select = h("select", { "aria-label": "Student", onchange: (event) => {
    state.student = state.students.find((s) => s.id === event.target.value);
    localStorage.setItem(`pramana.student.${state.course.id}`, state.student.id);
    route();
  } }, state.students.map((s) => h("option", { value: s.id, selected: s.id === state.student.id }, s.name)));
  const add = h("button.btn.sm", { onclick: async () => {
    const name = prompt("Name of the new student");
    if (!name) return;
    const student = await api(coursePath("/students"), { name });
    state.students.push(student);
    state.student = student;
    localStorage.setItem(`pramana.student.${state.course.id}`, student.id);
    renderWho();
    location.hash = "#/practice";
    route();
  } }, "New student");
  document.getElementById("who").replaceChildren(h("label", "Studying as"), select, h("div.row", add));
}

export async function refreshOverview() {
  state.overview = await api(coursePath("/overview"));
  return state.overview;
}

async function route(retried = false) {
  const id = (location.hash.replace(/^#\//, "").split("/")[0]) || "tutor";
  const section = sections.find((s) => s.id === id) || sections[0];
  renderNav(section.id);
  closeViewer();
  const view = document.getElementById("view");
  view.replaceChildren(h("div.empty", "Loading…"));
  try {
    const content = await section.view();
    view.replaceChildren(content);
    view.scrollTop = 0;
  } catch (error) {
    if (!retried && /unknown student/.test(String(error.message))) {
      // The remembered student was deleted elsewhere: pick up the current list and try once more.
      localStorage.removeItem(`pramana.student.${state.course.id}`);
      await loadStudents();
      return route(true);
    }
    view.replaceChildren(h("div.empty", h("h2", "Something went wrong"), h("p", String(error.message || error))));
  }
}

async function boot() {
  const courses = await api("/courses");
  if (!courses.length) {
    document.getElementById("view").replaceChildren(h("div.empty",
      h("h1", "No course yet"),
      h("p", "Build the sample course first: "), h("p.mono", "pramana fetch mechanics && pramana ingest mechanics && pramana bank mechanics")));
    return;
  }
  state.course = courses[0];
  document.title = `Pramana · ${state.course.title}`;
  await refreshOverview();
  await loadStudents();
  window.addEventListener("hashchange", () => route());
  route();
}

boot().catch((error) => toast(`Could not start: ${error.message}`));
