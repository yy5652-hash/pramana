// Flattens the film's clock (film/src/timing.ts) into film/src/generated/timeline.json, checks
// that no narration line runs into the next one or past its shot, and writes the subtitles.
//   node tools/timeline.mjs
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { FPS, S4, SHOTS, SHOT_START, TOTAL_FRAMES } from "../film/src/timing.ts";

const FILM = join(dirname(fileURLToPath(import.meta.url)), "../film");
const script = JSON.parse(readFileSync(join(FILM, "src/script.json"), "utf8"));
const voice = JSON.parse(readFileSync(join(FILM, "src/generated/voice.json"), "utf8"));
const text = (id) => (typeof script.lines[id] === "string" ? script.lines[id] : script.lines[id].text);

const shots = SHOTS.map((shot) => ({ id: shot.id, start: SHOT_START[shot.id] / FPS, seconds: shot.seconds }));
const cues = SHOTS.flatMap((shot) => shot.cues.map((cue) => ({
  line: cue.line, shot: shot.id, start: SHOT_START[shot.id] / FPS + cue.at, seconds: voice[cue.line], text: text(cue.line),
})));
let problems = 0;
cues.forEach((cue, i) => {
  const shot = shots.find((s) => s.id === cue.shot);
  const end = cue.start + cue.seconds;
  if (i + 1 < cues.length && end > cues[i + 1].start - 0.15) { problems += 1; console.log(`OVERLAP ${cue.line} ends ${end.toFixed(2)} but ${cues[i + 1].line} starts ${cues[i + 1].start.toFixed(2)}`); }
  if (end > shot.start + shot.seconds + 0.05) { problems += 1; console.log(`OVERRUN ${cue.line} ends ${end.toFixed(2)} after ${shot.id} ends ${(shot.start + shot.seconds).toFixed(2)}`); }
});
const total = TOTAL_FRAMES / FPS;
// Where the real lecture is heard: the music and narration make room there.
const s4 = shots.find((s) => s.id === "S4").start;
const lecture = [
  { start: 0, end: 12.0 },
  { start: s4 + S4.cut, end: s4 + S4.cut + S4.footage + 0.4 },
  { start: shots.find((s) => s.id === "S9").start, end: shots.find((s) => s.id === "S9").start + 4.4 },
];
writeFileSync(join(FILM, "src/generated/timeline.json"), JSON.stringify({ fps: FPS, seconds: total, shots, cues, lecture }, null, 1));

const stamp = (t) => { const ms = Math.round(t * 1000); const p = (n, w = 2) => String(n).padStart(w, "0"); return `${p(Math.floor(ms / 3600000))}:${p(Math.floor(ms / 60000) % 60)}:${p(Math.floor(ms / 1000) % 60)},${p(ms % 1000, 3)}`; };
const srt = cues.map((cue, i) => `${i + 1}\n${stamp(cue.start)} --> ${stamp(cue.start + cue.seconds + 0.25)}\n${cue.text}\n`).join("\n");
writeFileSync(join(FILM, "out/pramana-film.srt"), srt);
console.log(`${shots.length} shots, ${cues.length} lines, ${total.toFixed(1)} s (${Math.floor(total / 60)}:${String(Math.round(total % 60)).padStart(2, "0")}); ${problems} timing problems`);
