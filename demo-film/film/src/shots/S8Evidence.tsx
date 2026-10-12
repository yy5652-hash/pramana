import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Tag, Words } from "../components/Type";
import film from "../../public/data/film.json";
import { S8 } from "../timing";
import { color, ease, font, ramp, sec } from "../theme";

// The science, as a ledger: every measurement next to the command that reproduces it.
// Nothing here is typed in. Each row is read from evaluation/results/*.json (exported into
// public/data/film.json), and a row whose result file does not exist is simply not drawn.
const results = film.results as any;
const SYLLABUS = "#8aa0ff";

type Row = { key: string; label: string; note: string; command: string; bars: { value: number; shown: string; tag?: string; tone?: string }[] };
const percent = (value: number) => `${Math.round(value * 100)}%`;

const rows: Row[] = [];
const retrieval = results.retrieval?.full?.modes?.["hybrid + rerank"];
if (retrieval) {
  rows.push({ key: "retrieval", label: "The right source, in the top three", note: `${results.retrieval.n_questions} questions whose page, slide or second is known`, command: "evaluation.retrieval",
    bars: [{ value: retrieval["hit@3"].mean, shown: percent(retrieval["hit@3"].mean) }] });
}
const ragas = results.ragas;
if (ragas) {
  const judged = `${String(ragas.framework).replace("ragas ", "RAGAS ")} · ${ragas.n_scored} answers to ${ragas.n_in_material} questions · judged by a second model`;
  const metric = (name: string) => ({ value: ragas.metrics[name].mean, shown: ragas.metrics[name].mean.toFixed(2) });
  rows.push({ key: "faithfulness", label: "Faithfulness", note: judged, command: "evaluation.ragas_eval", bars: [metric("faithfulness")] });
  rows.push({ key: "relevancy", label: "Answer relevancy", note: "the same answers, the same judge", command: "evaluation.ragas_eval", bars: [metric("answer_relevancy")] });
  rows.push({ key: "precision", label: "Context precision", note: "how much of what was retrieved the answer needed", command: "evaluation.ragas_eval", bars: [metric("llm_context_precision_with_reference")] });
}
const ablation = results.ablation;
if (ablation) {
  rows.push({ key: "recall", label: "Context recall", note: `${ablation.n_questions} questions · the same course, read with and without vision`, command: "evaluation.ablation",
    bars: [{ value: ablation.full.mean, shown: ablation.full.mean.toFixed(2), tag: "with vision" }, { value: ablation.no_vision.mean, shown: ablation.no_vision.mean.toFixed(2), tag: "text only", tone: color.dim }] });
}
const grounding = results.grounding;
if (grounding) {
  const refusal = grounding.refusal;
  rows.push({ key: "declined", label: "Questions outside the course, declined", note: `and ${refusal.in_material_declined} of ${grounding.n_in_material} course questions declined by mistake`, command: "evaluation.grounding",
    bars: [{ value: refusal.off_material_declined / grounding.n_off_material, shown: `${refusal.off_material_declined} / ${grounding.n_off_material}` }] });
  const support = grounding.citation_support;
  if (support.segments_judged) {
    rows.push({ key: "supported", label: "Cited sentences their source fully supports", note: `${support.segments_judged} sentences, each checked against the passage it cites`, command: "evaluation.grounding",
      bars: [{ value: support.fully_supported, shown: percent(support.fully_supported) }] });
  }
}

const ROW_H = Math.min(128, 760 / Math.max(rows.length, 1));
const arrives = (row: Row) => S8.at[row.key] ?? S8.students;

const Line: React.FC<{ row: Row; index: number; at: number; next: number }> = ({ row, index, at, next }) => {
  const frame = useCurrentFrame();
  const enter = ramp(frame, at, at + 14);
  const rest = 1 - 0.42 * ramp(frame, next - 4, next + 10);        // earlier rows step back when the next one arrives
  return (
    <div style={{ position: "absolute", left: 120, top: 214 + index * ROW_H, width: 1680, height: ROW_H, opacity: enter * rest, transform: `translateY(${(1 - enter) * 16}px)` }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: 780 }}>
        <div style={{ fontFamily: font.serif, fontSize: ROW_H > 118 ? 40 : 36, color: color.chalk, lineHeight: 1.15 }}>{row.label}</div>
        <div style={{ fontFamily: font.sans, fontSize: 22, color: color.dim, marginTop: 5 }}>{row.note}</div>
      </div>
      <div style={{ position: "absolute", left: 820, top: row.bars.length > 1 ? 0 : 14, width: 860 }}>
        {row.bars.map((bar, k) => {
          const grow = ramp(frame, at + 6 + k * 8, at + 40 + k * 8, ease);
          return (
            <div key={k} style={{ display: "grid", gridTemplateColumns: "1fr 190px", alignItems: "center", gap: 28, marginBottom: 12 }}>
              <div style={{ position: "relative", height: row.bars.length > 1 ? 12 : 16, borderRadius: 8, background: "#1c1b19" }}>
                <div style={{ width: `${bar.value * grow * 100}%`, height: "100%", borderRadius: 8, background: bar.tone ?? color.cite, boxShadow: bar.tone ? undefined : `0 0 16px ${color.cite}` }} />
              </div>
              <div style={{ fontFamily: font.serif, fontSize: row.bars.length > 1 ? 40 : 56, color: bar.tone ?? color.chalk, fontVariantNumeric: "tabular-nums", lineHeight: 1, whiteSpace: "nowrap" }}>
                {bar.shown}
                {bar.tag ? <span style={{ fontFamily: font.mono, fontSize: 18, letterSpacing: "0.04em", color: color.dim, marginLeft: 12 }}>{bar.tag}</span> : null}
              </div>
            </div>
          );
        })}
        <div style={{ fontFamily: font.mono, fontSize: 19, letterSpacing: "0.04em", color: color.faint, marginTop: 2 }}>$ python -m {row.command}</div>
      </div>
    </div>
  );
};

// ---- simulated students: mastery gained, by kind of student and by how questions were chosen ----
const simulation = results.simulation;
const structured = simulation?.learners?.structured;
const POLICIES = [["adaptive", "Pramana (adaptive)", color.cite], ["sequential", "Syllabus order", SYLLABUS], ["random", "Random questions", color.dim]] as const;

const Students: React.FC<{ at: number }> = ({ at }) => {
  const frame = useCurrentFrame();
  if (!structured) return null;
  const cells = Object.values(structured.cells) as any[];
  const profiles = [...new Set(cells.map((cell) => cell.profile as string))];
  const cell = (profile: string, policy: string) => cells.find((c) => c.profile === profile && c.policy === policy).gain as { mean: number; ci95: number };
  const gain = (profile: string, policy: string) => cell(profile, policy).mean;
  const all = cells.map((c) => c.gain.mean as number);
  const top = Math.max(...all), bottom = Math.min(0, ...all);
  const W = 1100, H = 560, groupW = W / profiles.length, barW = 36;
  const y = (value: number) => 20 + ((top - value) / (top - bottom)) * (H - 40);
  const summary = structured.summary;
  const better = Math.round((summary.adaptive.gain / summary.random.gain - 1) * 100);
  const MARGIN = 0.01;      // a difference in mastery smaller than this is called a tie
  const wins = profiles.filter((p) => gain(p, "adaptive") > gain(p, "sequential") + MARGIN);
  const losses = profiles.filter((p) => gain(p, "adaptive") < gain(p, "sequential") - MARGIN);
  const list = (names: string[]) => names.map((name) => `“${name}”`).join(" and ");
  return (
    <div style={{ position: "absolute", left: 120, top: 214, width: 1680, opacity: ramp(frame, at, at + 16) }}>
      <Tag at={at} size={24} fill={color.dim}>{`SIMULATED STUDENTS · ${simulation.students_per_cell * profiles.length * POLICIES.length} RUNS · ${simulation.sessions} SESSIONS OF ${simulation.questions_per_session} QUESTIONS · MASTERY GAINED`}</Tag>
      <svg width={W} height={H + 70} style={{ marginTop: 26, overflow: "visible" }}>
        <line x1={0} x2={W} y1={y(0)} y2={y(0)} stroke="#34322e" strokeWidth={2} />
        {profiles.map((profile, p) => (
          <g key={profile} transform={`translate(${p * groupW + groupW / 2}, 0)`}>
            {POLICIES.map(([policy, , tone], k) => {
              const value = gain(profile, policy);
              const grow = ramp(frame, at + 14 + p * 5 + k * 3, at + 44 + p * 5 + k * 3, ease);
              const x = (k - 1) * (barW + 8) - barW / 2;
              const height = Math.abs(y(value) - y(0)) * grow;
              const spread = Math.abs(y(cell(profile, policy).ci95) - y(0));        // 95 % interval across the simulated students
              const tip = value >= 0 ? y(0) - height : y(0) + height;
              return (
                <g key={policy}>
                  <rect x={x} y={value >= 0 ? y(0) - height : y(0)} width={barW} height={height} rx={5} fill={tone} style={policy === "adaptive" ? { filter: `drop-shadow(0 0 8px ${color.cite})` } : undefined} />
                  <line x1={x + barW / 2} x2={x + barW / 2} y1={tip - spread} y2={tip + spread} stroke={color.chalk} strokeWidth={2} opacity={0.75 * ramp(frame, at + 50 + p * 5, at + 62 + p * 5)} />
                </g>
              );
            })}
            {profile.split(", ").map((part, i) => (
              <text key={part} x={0} y={H + 26 + i * 26} fill={color.dim} fontFamily={font.sans} fontSize={22} textAnchor="middle">{part}</text>
            ))}
          </g>
        ))}
      </svg>
      <div style={{ position: "absolute", left: 1170, top: 64, width: 510 }}>
        {POLICIES.map(([policy, name, tone], i) => (
          <div key={policy} style={{ display: "flex", alignItems: "baseline", gap: 16, marginBottom: 18, opacity: ramp(frame, at + 40 + i * 8, at + 54 + i * 8) }}>
            <span style={{ width: 20, height: 20, borderRadius: 5, background: tone, display: "inline-block", transform: "translateY(1px)", flex: "none" }} />
            <span style={{ fontFamily: font.sans, fontSize: 32, color: color.chalk, width: 300 }}>{name}</span>
            <span style={{ fontFamily: font.serif, fontSize: 42, color: policy === "adaptive" ? color.cite : color.chalk, fontVariantNumeric: "tabular-nums" }}>+{summary[policy].gain.toFixed(3)}</span>
          </div>
        ))}
        <div style={{ fontFamily: font.sans, fontSize: 28, lineHeight: 1.42, color: "#bdb8ad", marginTop: 26, opacity: ramp(frame, at + 84, at + 100) }}>
          {`${better}% more than random practice. Against plain syllabus order it is ahead for ${list(wins)}${losses.length ? ` and behind for ${list(losses)}` : ""}. Both are in the report.`}
        </div>
        <div style={{ fontFamily: font.mono, fontSize: 19, letterSpacing: "0.04em", color: color.faint, marginTop: 22, opacity: ramp(frame, at + 84, at + 100) }}>$ python -m evaluation.simulate</div>
      </div>
    </div>
  );
};

export const S8Evidence: React.FC = () => {
  const frame = useCurrentFrame();
  const students = sec(S8.students);
  const leave = ramp(frame, students - 14, students);
  return (
    <AbsoluteFill style={{ background: color.black }}>
      <div style={{ position: "absolute", left: 120, top: 84 }}>
        <Words text="Measured, not claimed." at={6} size={76} accent={["Measured"]} />
      </div>
      <div style={{ opacity: 1 - leave, transform: `translateY(${-leave * 20}px)` }}>
        {rows.map((row, index) => <Line key={row.key} row={row} index={index} at={sec(arrives(row))} next={sec(index + 1 < rows.length ? arrives(rows[index + 1]) : S8.students)} />)}
      </div>
      <Students at={students} />
      <div style={{ position: "absolute", left: 120, bottom: 70, opacity: ramp(frame, sec(S8.close) - 4, sec(S8.close) + 12) }}>
        <Words text="Every number in this film is in the repository, with the command that reproduces it." at={sec(S8.close)} size={40} fill={color.chalk} stagger={2} />
      </div>
    </AbsoluteFill>
  );
};
