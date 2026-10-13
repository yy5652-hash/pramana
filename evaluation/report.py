"""Turn evaluation/results/*.json into the tables people read.

Writes `docs/results.md` in full and replaces the block between the `results` markers in
`README.md`, so no number in the documentation is typed by hand.

    python -m evaluation.report --course mechanics
"""
from __future__ import annotations

import argparse
import json
import re

from pramana.config import ROOT
from pramana.db import open_course
from pramana.stats import course_stats

from .common import RESULTS

RAGAS_NAMES = {
    "faithfulness": "Faithfulness", "answer_relevancy": "Answer relevancy",
    "llm_context_precision_with_reference": "Context precision", "context_recall": "Context recall",
}


def load() -> dict:
    return {path.stem: json.loads(path.read_text()) for path in sorted(RESULTS.glob("*.json"))}


def pm(value: dict | None, digits: int = 2) -> str:
    if not value or value.get("mean") is None:
        return "–"
    return f"{value['mean']:.{digits}f} ± {value['ci95']:.{digits}f}"


def knowledge_base(stats: dict) -> list[str]:
    total = stats["units"]
    lines = ["## Knowledge base", "",
             f"{sum(stats['sources'].values())} sources ({stats['sources'].get('textbook', 0)} textbook, {stats['sources'].get('slides', 0)} slide decks, "
             f"{stats['sources'].get('video', 0)} lecture videos) became **{total} citable units**; {stats['units_tagged']} are tagged to one of "
             f"{stats['concepts']} concepts in {stats['topics']} topics, linked by {stats['prerequisite_edges']} prerequisite edges.", "",
             "| How the unit was obtained | Units | Share |", "|---|---:|---:|"]
    labels = {"text": "PDF text layer or slide text alone", "vision": "needed the vision model (equations, figures, slide pictures, the board)", "speech": "speech recognition"}
    for key in ("text", "vision", "speech"):
        n = stats["units_by_modality"].get(key, 0)
        lines.append(f"| {labels[key]} | {n} | {n / total:.0%} |")
    lines += ["", "| Kind of unit | Count |", "|---|---:|"]
    names = {"text": "textbook passages", "figure": "textbook figures", "slide": "slides", "transcript": "spoken lecture passages", "frame": "board readings"}
    lines += [f"| {names.get(k, k)} | {v} |" for k, v in sorted(stats["units_by_kind"].items(), key=lambda kv: -kv[1])]
    return lines


def bank(stats: dict) -> list[str]:
    verified = sum(stats["questions_verified"].values())
    rejected = sum(stats["questions_rejected"].values())
    lines = ["## Question bank", "",
             f"{verified + rejected} well-formed questions were drafted; **{verified} passed every check and {rejected} ({rejected / max(verified + rejected, 1):.0%}) were rejected** before any student could see them.", "",
             "| Rejected because | Count |", "|---|---:|"]
    lines += [f"| {reason} | {n} |" for reason, n in sorted(stats["questions_rejected"].items(), key=lambda kv: -kv[1])]
    lines += ["", "| Verified questions | " + " | ".join(stats["questions_verified"]) + " | total |", "|---|" + "---:|" * (len(stats["questions_verified"]) + 1),
              "| by type | " + " | ".join(str(v) for v in stats["questions_verified"].values()) + f" | {verified} |", "",
              "| Difficulty | " + " | ".join(str(k) for k in sorted(stats["questions_by_difficulty"])) + " |", "|---|" + "---:|" * len(stats["questions_by_difficulty"]),
              "| questions | " + " | ".join(str(stats["questions_by_difficulty"][k]) for k in sorted(stats["questions_by_difficulty"])) + " |"]
    return lines


def retrieval(r: dict) -> list[str]:
    lines = ["## Retrieval against known source locations", "",
             f"{r['n_questions']} in-material questions. A hit at rank *k* means one of the top *k* results sits at the exact page, slide or lecture passage the question was written from.", "",
             "| Retriever | hit@1 | hit@3 | hit@6 | MRR |", "|---|---:|---:|---:|---:|"]
    for name, m in r["full"]["modes"].items():
        shown = f"**{name}** (used by the tutor)" if name == "hybrid + rerank" else name
        lines.append(f"| {shown} | {pm(m['hit@1'])} | {pm(m['hit@3'])} | {pm(m['hit@6'])} | {pm(m['mrr'])} |")
    if "no_vision" in r:
        m = r["no_vision"]["modes"]["hybrid + rerank"]
        lines.append(f"| same pipeline, knowledge base built without vision ({r['no_vision']['units']} units) | {pm(m['hit@1'])} | {pm(m['hit@3'])} | {pm(m['hit@6'])} | {pm(m['mrr'])} |")
    lines += ["", "| Where the answer lives | n | hit@1 | hit@3 | hit@6 |", "|---|---:|---:|---:|---:|"]
    for name, m in r["full"]["by_stratum"].items():
        lines.append(f"| {name} | {m['hit@3']['n']} | {m['hit@1']['mean']:.2f} | {m['hit@3']['mean']:.2f} | {m['hit@6']['mean']:.2f} |")
    return lines


def ablation(a: dict) -> list[str]:
    lines = ["## What vision buys: context recall with and without it", "",
             f"{a['metric']} on {a['n_questions']} in-material questions, top {a['contexts_per_question']} contexts: the share of the reference answer's claims found in the retrieved text. "
             "The no-vision knowledge base reads only PDF text layers, slide text and speech.", "",
             "| Where the answer lives | n | with vision | without vision |", "|---|---:|---:|---:|"]
    for stratum, both in a["by_stratum"].items():
        lines.append(f"| {stratum} | {both['full']['n']} | {pm(both['full'])} | {pm(both['no_vision'])} |")
    lines.append(f"| **all** | {a['full']['n']} | **{pm(a['full'])}** | **{pm(a['no_vision'])}** |")
    return lines


def grounding(g: dict) -> list[str]:
    r, s, loc = g["refusal"], g["citation_support"], g["citation_location"]["answers_citing_gold_location"]
    lines = ["## Grounding", "",
             "| | answered | declined |", "|---|---:|---:|",
             f"| In the material ({g['n_in_material']} questions) | {r['in_material_answered']} | {r['in_material_declined']} |",
             f"| Not in the material ({g['n_off_material']} questions) | {r['off_material_answered']} | {r['off_material_declined']} |", "",
             f"Off-material questions from another subject: {r['by_distance']['far']['declined']}/{r['by_distance']['far']['n']} declined. "
             f"Physics the ingested chapters do not teach: {r['by_distance']['near']['declined']}/{r['by_distance']['near']['n']} declined.", "",
             f"**Citation support.** {s['segments_judged']} answer segments were each read by a second model next to the excerpts they cite: "
             f"{s['fully_supported']:.0%} fully supported, {s['partly_supported']:.0%} partly, {s['unsupported']:.0%} unsupported.", "",
             *([f"**A check on that judge.** The same segments were shown again next to the excerpts a different answer cites. "
                f"Of {s['judge_control']['segments_judged']} such mismatched pairs the judge called {s['judge_control']['unsupported']:.0%} unsupported, "
                f"{s['judge_control']['partly_supported']:.0%} partly supported and {s['judge_control']['fully_supported']:.0%} fully supported "
                "(some pairs do overlap: a course repeats itself).", ""] if s.get("judge_control") else []),
             f"**Citation location.** {loc['mean']:.0%} of answers (n = {loc['n']}) cite the exact gold location. Citing the same fact from another source counts as a miss here.", "",
             f"Segments the model wrote without a valid source, removed by code before display: {g['unsourced_segments_removed']}."]
    if r["answered_off_material"]:
        lines += ["", "Off-material questions that were answered anyway:"] + [f"- *{a['question']}* ({a['coverage']})" for a in r["answered_off_material"]]
    if r["declined_in_material"]:
        lines += ["", "In-material questions that were declined:"] + [f"- *{a['question']}* ({a['stratum']})" for a in r["declined_in_material"]]
    return lines


def ragas(r: dict) -> list[str]:
    lines = ["## Answer quality (RAGAS)", "",
             f"{r['framework']}, {r['n_scored']} answered in-material questions of {r['n_in_material']}, top {r['contexts_per_question']} contexts each. "
             f"Judge: {', '.join(r['judge_models'])}. Tutor: {', '.join(r['tutor_models'])}. Mean ± 95 % interval.", "",
             "| Metric | Score | Unscored |", "|---|---:|---:|"]
    for name, m in r["metrics"].items():
        lines.append(f"| {RAGAS_NAMES.get(name, name)} | {pm(m)} | {r['unscored'].get(name, 0)} |")
    lines += ["", "| Where the answer lives | " + " | ".join(RAGAS_NAMES.get(n, n) for n in r["metrics"]) + " |", "|---|" + "---:|" * len(r["metrics"])]
    for stratum, metrics in r["by_stratum"].items():
        lines.append(f"| {stratum} | " + " | ".join("–" if m["mean"] is None else f"{m['mean']:.2f}" for m in metrics.values()) + " |")
    return lines


def lessons(r: dict) -> list[str]:
    s, made = r["narration_support"], r["lessons_made"]
    lines = ["## Lessons", "",
             f"A storyboard was written for each of {r['concepts']} concepts, for a new student. **{made} lessons** could be made"
             + (f"; {len(r['too_little_material'])} concepts had too little material" if r["too_little_material"] else "") + ". No film is cut for this measurement.", "",
             "| | |", "|---|---:|",
             f"| Teaching scenes kept (each names a source it was given, once) | {r['scenes_kept']} |",
             f"| Scenes, steps or points dropped by code | {r['scenes_dropped']} |",
             f"| Teaching scenes per lesson | {pm(r['scenes_per_lesson'], 1)} |"]
    if "lessons_with_a_worked_example" in r:
        lines += [f"| Lessons that walk through a worked example from the textbook | {r['lessons_with_a_worked_example']} of {made} ({r['example_steps']} steps) |",
                  f"| Lessons that take up a mistake (for a new student, one the question bank marks as common) | {r['lessons_with_a_mistake']} of {made} |",
                  f"| Lessons that end on a recap | {r['lessons_with_a_recap']} of {made} ({r['recap_points']} points) |",
                  f"| Lessons that end on a checked question the student has not met | {r['lessons_ending_on_a_question']} of {made} |"]
    lines += [f"| Textbook scenes whose quoted words were found in the passage, word for word | {r['textbook_scenes_with_verified_quote']} of {r['textbook_scenes']} |",
              f"| Lessons in which the student hears the lecturer | {r['lessons_with_the_lecturers_voice']} of {made} |",
              f"| Words spoken per lesson | {pm(r['narration_words_per_lesson'], 0)} |"]
    if "seconds_per_lesson_about" in r:
        lines.append(f"| Length of a lesson, estimated from its words and clips | {pm(r['seconds_per_lesson_about'], 0)} s |")
    if "own_mistake_found" in r:
        own = r["own_mistake_found"]
        lines.append(f"| A student's own wrong answer found and taken up (one student per concept, no model involved) | {own['found']} of {own['concepts']} |")
    lines += ["", "Scenes by what they show: " + ", ".join(f"{name} {n}" for name, n in sorted(r["kinds"].items(), key=lambda kv: -kv[1])) + "."]
    if r["dropped_because"]:
        lines += ["", "Dropped because: " + "; ".join(f"{why} ({n})" for why, n in r["dropped_because"].items()) + "."]
    if s["lines_judged"]:
        lines += ["", f"**Is what the lesson says supported by what it rests on?** {s['lines_judged']} spoken lines were each read by a second model "
                      f"({', '.join(r['models']['judge'])}) next to their source: {s['fully_supported']:.0%} fully supported, "
                      f"{s['partly_supported']:.0%} partly, {s['unsupported']:.0%} unsupported. Script written by {', '.join(r['models']['script'])}."]
        if r.get("support_by_part"):
            name = {"teaching": "Teaching scenes, against the source on screen", "example": "Steps of the worked example, against the textbook's own",
                    "mistake": "The words about the mistake, against the question bank's record of it", "recap": "Points of the recap, against the source they name"}
            lines += ["", "| Part | Lines | Fully supported | Partly | Unsupported |", "|---|---:|---:|---:|---:|"]
            lines += [f"| {name.get(part, part)} | {v['lines_judged']} | {v['fully_supported']:.0%} | {v['partly_supported']:.0%} | {v['unsupported']:.0%} |"
                      for part, v in r["support_by_part"].items()]
    return lines


def simulation(sim: dict) -> list[str]:
    runs = sim["students_per_cell"] * len(sim["learners"]["structured"]["cells"])
    lines = ["## Simulated students", "",
             f"{runs} simulated students per learner type ({sim['students_per_cell']} per profile and policy), {sim['sessions']} daily sessions of {sim['questions_per_session']} questions "
             f"from the real bank ({sim['bank']} questions, {sim['concepts']} concepts). Gain is the change in mean true proficiency from the start to the day after the last session."]
    for kind, title in (("structured", "Structured learner (prerequisites and difficulty matter)"), ("flat", "Flat learner (they do not): the ablation")):
        block = sim["learners"][kind]
        lines += ["", f"### {title}", "", "| Student profile | adaptive | syllabus order | random |", "|---|---:|---:|---:|"]
        for profile in dict.fromkeys(c["profile"] for c in block["cells"].values()):
            cells = [block["cells"][f"{profile}|{p}"]["gain"] for p in ("adaptive", "sequential", "random")]
            best = max(c["mean"] for c in cells)
            lines.append(f"| {profile} | " + " | ".join((f"**{c['mean']:+.3f}**" if c["mean"] == best else f"{c['mean']:+.3f}") + f" ± {c['ci95']:.3f}" for c in cells) + " |")
        s = block["summary"]
        lines.append(f"| **all profiles** | **{s['adaptive']['gain']:+.3f}** | **{s['sequential']['gain']:+.3f}** | **{s['random']['gain']:+.3f}** |")
        lines += ["", "| How well the learner model knows the student | adaptive | syllabus order | random |", "|---|---:|---:|---:|",
                  "| prediction error on a probe item, after session 1 | " + " | ".join(f"{s[p]['probe_error_first_session']:.3f}" for p in ("adaptive", "sequential", "random")) + " |",
                  f"| prediction error on a probe item, after session {sim['sessions']} | " + " | ".join(f"{s[p]['probe_error_last_session']:.3f}" for p in ("adaptive", "sequential", "random")) + " |",
                  "| same, with no learner model (prior only) | " + " | ".join(f"{s[p]['probe_error_without_model']:.3f}" for p in ("adaptive", "sequential", "random")) + " |",
                  "| overlap of the five weakest concepts, estimated vs true | " + " | ".join(f"{s[p]['weakest5_last_session']:.2f}" for p in ("adaptive", "sequential", "random")) + " |",
                  "| questions served that the student had already seen | " + " | ".join(f"{s[p]['exact_repeat_rate']:.1%}" for p in ("adaptive", "sequential", "random")) + " |"]
    return lines


STAGES = {
    "ingest-pages": "Reading textbook pages (vision)", "ingest-slides": "Reading slides (vision)", "ingest-frames": "Reading the board in lecture frames (vision)",
    "ingest-map": "Writing the concept map", "ingest-tags": "Tagging units with concepts",
    "questions-generate": "Writing questions", "questions-verify": "Solving questions blind (verification)",
    "eval-testset": "Drafting test-set questions", "eval-answers": "Tutor answers on the test set",
    "eval-citation-judge": "Judging citation support", "eval-ragas": "RAGAS judge (answer quality and the vision ablation)",
    "lesson-script": "Writing lesson storyboards", "eval-lesson-judge": "Judging lesson narration",
}


def models_used() -> list[str]:
    """Which model wrote the cached replies of each stage. Read from the cache itself."""
    from collections import Counter

    from pramana.config import settings
    lines = ["## Which model did what", "",
             "Counted from the cached replies in `data/llm_cache/`, which are what `make replay` reads. A stage lists more than one model "
             "when the first choice was out of quota or overloaded and the client moved down its fallback chain.", "",
             "| Stage | Replies | Models |", "|---|---:|---|"]
    for namespace, title in STAGES.items():
        path = settings.cache_dir / f"{namespace}.jsonl"
        if not path.exists():
            continue
        models = Counter(json.loads(line)["model"] for line in path.read_text().splitlines() if line.strip())
        lines.append(f"| {title} | {sum(models.values())} | " + ", ".join(f"{name} ({n})" for name, n in models.most_common()) + " |")
    lines += ["", "Speech was transcribed locally (Whisper `small.en`); embeddings and re-ranking are local models too."]
    return lines


def summary(results: dict, stats: dict) -> list[str]:
    """The short table for the README."""
    rows = [(f"Citable units from {sum(stats['sources'].values())} sources", f"{stats['units']} ({stats['units_by_modality'].get('vision', 0) / stats['units']:.0%} needed vision to read)")]
    verified, rejected = sum(stats["questions_verified"].values()), sum(stats["questions_rejected"].values())
    rows.append(("Questions verified / rejected before use", f"{verified} / {rejected}"))
    if "retrieval" in results:
        m = results["retrieval"]["full"]["modes"]["hybrid + rerank"]
        rows.append((f"Retrieval hits the exact page, slide or passage (n = {results['retrieval']['n_questions']})", f"hit@1 {m['hit@1']['mean']:.2f}, hit@3 {m['hit@3']['mean']:.2f}, MRR {m['mrr']['mean']:.2f}"))
    if "ablation" in results:
        a = results["ablation"]
        rows.append((f"Context recall with vision / without (n = {a['n_questions']})", f"{a['full']['mean']:.2f} / {a['no_vision']['mean']:.2f}"))
    if "ragas" in results:
        m = results["ragas"]["metrics"]
        rows.append((f"RAGAS (n = {results['ragas']['n_scored']})", ", ".join(f"{RAGAS_NAMES.get(k, k).lower()} {v['mean']:.2f}" for k, v in m.items() if v["mean"] is not None)))
    if "grounding" in results:
        g = results["grounding"]
        rows.append(("Off-material questions declined", f"{g['refusal']['off_material_declined']} of {g['n_off_material']}"))
        rows.append(("In-material questions answered", f"{g['refusal']['in_material_answered']} of {g['n_in_material']}"))
        rows.append(("Answer segments fully supported by their own citations", f"{g['citation_support']['fully_supported']:.0%} of {g['citation_support']['segments_judged']}"))
    if "lessons" in results:
        r = results["lessons"]
        extra = f"{r['lessons_with_a_worked_example']} with a worked example from the textbook; " if "lessons_with_a_worked_example" in r else ""
        rows.append(("Lesson films: spoken lines supported by what they rest on",
                     f"{r['narration_support']['fully_supported']:.0%} of {r['narration_support']['lines_judged']} ({r['lessons_made']} lessons; {extra}{r['scenes_dropped']} scenes dropped by code)"))
        if "own_mistake_found" in r:
            rows.append(("Lesson films: a student's own wrong answer found and taken up", f"{r['own_mistake_found']['found']} of {r['own_mistake_found']['concepts']} concepts"))
    if "simulation" in results:
        block = results["simulation"]["learners"]["structured"]
        s = block["summary"]
        novice = {p: block["cells"][f"novice|{p}"]["gain"]["mean"] for p in ("adaptive", "sequential", "random")}
        rows.append((f"Simulated students: gain in true proficiency ({results['simulation']['students_per_cell'] * len(block['cells'])} runs)",
                     f"adaptive {s['adaptive']['gain']:+.3f} against {s['random']['gain']:+.3f} for random selection; for novices {novice['adaptive']:+.3f}, "
                     f"ahead of syllabus order ({novice['sequential']:+.3f}) and random ({novice['random']:+.3f})"))
        rows.append(("Repeated questions served by the selector", f"{s['adaptive']['exact_repeat_rate']:.1%}"))
    return ["| Measured | Result |", "|---|---|"] + [f"| {a} | {b} |" for a, b in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--course", default="mechanics")
    args = parser.parse_args()
    results = load()
    stats = course_stats(open_course(args.course))
    sections = [["# Results", "", "Generated by `python -m evaluation.report` from `evaluation/results/*.json`. Method and limits: [evaluation.md](evaluation.md)."],
                knowledge_base(stats), bank(stats)]
    for key, build in (("retrieval", retrieval), ("ablation", ablation), ("grounding", grounding), ("ragas", ragas), ("lessons", lessons), ("simulation", simulation)):
        sections.append(build(results[key]) if key in results else [f"## {key.title()}", "", "Not run yet."])
    sections.append(models_used())
    (ROOT / "docs" / "results.md").write_text("\n\n".join("\n".join(s) for s in sections) + "\n")
    readme = ROOT / "README.md"
    block = "<!-- results:start -->\n" + "\n".join(summary(results, stats)) + "\n<!-- results:end -->"
    text = readme.read_text()
    if "<!-- results:start -->" in text:
        readme.write_text(re.sub(r"<!-- results:start -->.*?<!-- results:end -->", lambda _: block, text, flags=re.S))
    print(f"wrote docs/results.md ({', '.join(sorted(results)) or 'no results yet'})")


if __name__ == "__main__":
    main()
