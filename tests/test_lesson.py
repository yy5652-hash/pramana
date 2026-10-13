"""Lessons: what is kept from a drafted storyboard, where a passage and a quote are found, and
that the film really is cut. No language model and no voice are involved."""
from __future__ import annotations

import numpy as np

from pramana.lesson import build, render, script, voice


def _unit(unit_id: str, kind: str, text: str) -> dict:
    return {"id": unit_id, "kind": kind, "text": text, "source_id": "book", "locator": {"page": 1, "rect": [0.1, 0.1, 0.9, 0.3]}}


def test_only_scenes_tied_to_a_source_survive():
    sources = [_unit("a", "text", "Friction is a contact force that opposes the motion or attempted motion between two systems."),
               _unit("b", "slide", "COEFFICIENT OF FRICTION. The frictional force is proportional to the normal force."),
               _unit("c", "figure", "FIGURE 6.11 A block on a rough surface, at rest and then moving.")]
    drafts = [
        {"source": "S1", "mode": "explain", "narration": "Friction is a contact force that opposes motion.", "focus": "Friction is a contact force that opposes the motion"},
        {"source": "S9", "mode": "explain", "narration": "There is no such source.", "focus": ""},
        {"source": "S1", "mode": "explain", "narration": "The same source a second time.", "focus": ""},
        {"source": "S2", "mode": "explain", "narration": "", "focus": ""},
        {"source": "[S3]", "mode": "explain", "narration": "The figure shows a block at rest and then moving.", "focus": "these words are not in the figure text"},
    ]
    scenes, dropped = script._grounded(None, "course", drafts, sources)
    assert [(s["unit_id"], s["kind"]) for s in scenes] == [("a", "read"), ("c", "figure")]
    assert scenes[0]["focus"] == "Friction is a contact force that opposes the motion"
    assert scenes[1]["focus"] == ""                       # only a textbook passage has words to light
    assert len(dropped) == 3


def test_a_quote_must_be_in_the_source_word_for_word():
    text = "The magnitude of static friction $f_s$ is\n\n$$ f_s \\le \\mu_s N $$\n\nwhere $\\mu_s$ is the coefficient of static friction."
    assert script._says(text, "the coefficient of static friction")
    assert script._says(text, "The magnitude of  static friction")           # case and spacing do not matter
    assert not script._says(text, "the coefficient of kinetic friction")
    assert not script._says(text, "friction")                                # too short to be a quote


def test_a_listen_scene_needs_its_words_in_the_lecture(monkeypatch, db):
    words = [{"w": f" {w}", "s": 100 + i * 0.4, "e": 100.3 + i * 0.4} for i, w in enumerate(
        "and this coefficient of static friction is slightly bigger than the coefficient of kinetic friction which explains the arrow".split())]
    db.insert("sources", {"id": "lecture", "kind": "video", "title": "Lecture", "file": "lecture.mp4", "licence": "", "attribution": "", "meta": {}})
    monkeypatch.setattr("pramana.ingest.video.transcribe", lambda path: words)
    spoken = {"id": "v:t1", "kind": "transcript", "source_id": "lecture", "text": "…", "locator": {"t_start": 100.0, "t_end": 108.0}}
    heard = {"source": "S1", "mode": "listen", "narration": "", "focus": "static friction is slightly bigger than the coefficient of kinetic friction"}
    scenes, dropped = script._grounded(db, "course", [heard], [spoken])
    assert scenes[0]["kind"] == "listen" and dropped == []
    assert 101.0 < scenes[0]["t0"] < 102.0 and scenes[0]["t1"] > scenes[0]["t0"] + 3
    invented = {**heard, "focus": "energy is conserved in every collision between two bodies"}
    scenes, dropped = script._grounded(db, "course", [invented], [spoken])
    assert scenes == [] and dropped


def test_a_passage_runs_on_to_the_next_unit_in_its_own_column(db):
    # A unit whose stored rectangle is only its heading line, with the next passage further down the page.
    db.insert("units", {"id": "book:p1:2", "source_id": "book", "kind": "text", "modality": "vision", "locator": {"page": 1, "rect": [0.13, 0.37, 0.43, 0.38]},
                        "section": "", "text": "### MAGNITUDE OF STATIC FRICTION", "asset": "", "ord": 10})
    db.insert("units", {"id": "book:p1:3", "source_id": "book", "kind": "text", "modality": "text", "locator": {"page": 1, "rect": [0.12, 0.59, 0.88, 0.70]},
                        "section": "", "text": "Next passage.", "asset": "", "ord": 11})
    db.insert("units", {"id": "book:p1:4", "source_id": "book", "kind": "text", "modality": "text", "locator": {"page": 1, "rect": [0.55, 0.40, 0.88, 0.45]},
                        "section": "", "text": "In the other column.", "asset": "", "ord": 12})
    x0, y0, x1, y1 = build.extent(db, db.one("SELECT * FROM units WHERE id = 'book:p1:2'"))
    assert (x0, x1) == (0.1, 0.9) and y0 == 0.37           # as wide as the passages it shares a column with
    assert 0.55 < y1 < 0.59                                # down to just above the next passage, not into it


def test_captions_cover_the_line_and_stay_inside_it():
    line = "Static friction is not one fixed number. It can be anything up to a maximum: the coefficient of static friction times the normal force."
    pieces = render.split_caption(line, seconds=8.0, lead=0.3)
    assert " ".join(p[2] for p in pieces) == line
    assert pieces[0][0] == 0.3 and abs(pieces[-1][1] - 8.3) < 0.05
    assert all(a[1] <= b[0] + 0.011 for a, b in zip(pieces, pieces[1:]))
    assert all(len(p[2].split()) <= 14 for p in pieces)


def test_the_narrator_is_given_words_not_markup():
    assert voice.spoken("The law is $F = ma$, so **force** ≥ 0.") == "The law is F equals ma, so force at least 0."


def test_a_film_is_cut_with_picture_and_sound(tmp_path):
    import av

    tone = (0.2 * np.sin(np.linspace(0, 440 * 2 * np.pi, render.RATE))).astype(np.float32)
    shots = [render.Shot(0.5, render.card([("A LESSON", "mono", 24, render.CITE), ("Friction", "serif", 70, render.CHALK)], rule=0), tone,
                         tag="Book · p. 1", number=1, captions=[(0.0, 0.4, "Friction opposes motion.")]),
             render.Shot(0.4, render.slide_shot(render.Image.new("RGB", (640, 480), (250, 250, 250)), 0.4), np.zeros(0, np.float32))]
    seconds = render.render(shots, tmp_path / "lesson.mp4")
    assert abs(seconds - 0.9) < 0.05
    with av.open(str(tmp_path / "lesson.mp4")) as film:
        assert (film.streams.video[0].width, film.streams.video[0].height) == (render.W, render.H)
        assert len(film.streams.audio) == 1
        assert sum(1 for _ in film.decode(video=0)) == 27


# ---- the longer lesson: formulas on cards, the worked example, the mistake, the closing question ----

def test_formulas_are_set_not_dropped():
    from pramana.lesson import typeset

    plain = typeset.formula("a = F/m", 30, render.CHALK)
    stacked = typeset.formula(r"a = \frac{F_{\text{net}}}{m}", 30, render.CHALK)
    assert stacked.up > 1.3 * plain.up and stacked.width < plain.width           # a fraction is stacked: taller, and narrower than a/b in a row
    assert typeset.formula(r"\vec{F}", 30, render.CHALK).up > typeset.formula("F", 30, render.CHALK).up     # the arrow sits over the letter
    assert typeset.formula(r"\nosuchcommand{x} + 1", 30, render.CHALK).width > 0     # an unknown command is shown, not fatal
    assert typeset.unit("m/s^2") == r"\text{m/s}^{2}" and typeset.unit("dimensionless") == ""
    laid = typeset.layout(r"Find $a$ if $F = 12\ \text{N}$ and $m = 3\ \text{kg}$, " * 6, 30, render.CHALK, 500)
    assert len(laid.lines) > 3 and laid.width <= 500
    wide = typeset.layout(r"$a = \frac{45.0\ \text{m/s} - 15.0\ \text{m/s}}{6.0\ \text{s}} = \frac{30.0\ \text{m/s}}{6.0\ \text{s}} = 5.0\ \text{m/s}^2$", 30, render.CHALK, 300)
    assert wide.width <= 300                                                    # a formula longer than the line is set smaller, never cut


def _passage(db, unit_id: str, ord_: int, text: str, concept: str | None = "velocity", page: int = 9) -> None:
    db.insert("units", {"id": unit_id, "source_id": "book", "kind": "text", "modality": "text", "locator": {"page": page, "rect": [0.1, 0.1 + 0.01 * ord_, 0.9, 0.2 + 0.01 * ord_]},
                        "section": "", "text": text, "asset": "", "ord": ord_})
    if concept:
        db.insert("unit_concepts", {"unit_id": unit_id, "concept_id": concept, "weight": 1.0})


def test_a_worked_example_is_found_by_the_parts_the_textbook_prints(db):
    _passage(db, "book:p9:1", 20, "EXAMPLE 3.2\nFinding velocity from a graph. Given the position-versus-time graph, find the velocity during each interval of the trip.")
    _passage(db, "book:p9:2", 21, "The graph has three straight lines.", concept=None)
    _passage(db, "book:p9:3", 22, "### Strategy\n\nThe graph contains three straight lines. We find the velocity during each interval by taking the slope of the line.")
    _passage(db, "book:p9:4", 23, "### Solution\n\nTime interval 0 s to 0.5 s: the slope is 1.0 m/s. Time interval 0.5 s to 1.0 s: the slope is 0.0 m/s, so the object is at rest.")
    _passage(db, "book:p9:5", 24, "### Significance\n\nDuring the first interval the object moves away from the origin, and during the second it does not move at all.")
    _passage(db, "book:p9:6", 25, "### Strategy\n\nA strategy with no solution after it is not a worked example and is never offered to a lesson.")
    parts = script.worked_example(db, "velocity")
    assert [(role, unit["id"]) for role, unit in parts] == [("problem", "book:p9:1"), ("strategy", "book:p9:3"), ("solution", "book:p9:4"), ("significance", "book:p9:5")]
    assert script.worked_example(db, "position") == []                          # nothing tagged with that concept
    left = script.worked_example(db, "velocity", exclude={"book:p9:1"})          # a part already on screen elsewhere is left out
    assert [role for role, _ in left] == ["strategy", "solution", "significance"]


def test_the_example_keeps_the_textbooks_order_and_needs_its_solution():
    example = [("problem", _unit("e1", "text", "A lawn mower is pushed with a net force of fifty one newtons and has a mass of twenty four kilograms.")),
               ("strategy", _unit("e2", "text", "Since the net force and the mass are given, the acceleration can be calculated directly from the second law.")),
               ("solution", _unit("e3", "text", "Entering known values gives $a = \\frac{51\\text{ N}}{24\\text{ kg}}$, which is 2.1 metres per second squared."))]
    drafts = [{"source": "E2", "narration": "The plan is to use the second law directly.", "focus": "the acceleration can be calculated directly"},
              {"source": "E1", "narration": "Out of order, so it is dropped.", "focus": ""},
              {"source": "E7", "narration": "No such part.", "focus": ""},
              {"source": "E3", "narration": "Fifty one newtons over twenty four kilograms is two point one metres per second squared.", "focus": "words that are not there at all"}]
    steps, dropped = script._steps(drafts, example)
    assert [(s["role"], s["unit_id"]) for s in steps] == [("strategy", "e2"), ("solution", "e3")]
    assert steps[0]["focus"] and steps[1]["focus"] == "" and len(dropped) == 2
    steps, dropped = script._steps(drafts[:1], example)                         # the strategy alone, with no solution: no example at all
    assert steps == [] and "without its solution" in dropped[-1]


def test_a_lesson_takes_up_the_students_own_mistake(db):
    from pramana.assess import session

    common = script.mistake(db, "s1", "velocity")                               # nothing answered yet: a mistake the bank marks as common
    assert common and not common["own"] and common["why"] == "confuses speed with velocity" and common["wrong"] == "A" and common["right"] == "B"
    sitting = session.start(db, "s1", "quiz", ["velocity"], n=1, types=["numeric"])
    session.answer(db, "course", sitting["assessment_id"], sitting["question"]["id"], "20")       # the key is 10 m/s
    own = script.mistake(db, "s1", "velocity")
    assert own["own"] and own["question_id"] == sitting["question"]["id"]
    assert own["wrong"] == r"$20\ \text{m/s}$" and own["right"] == r"$10\ \text{m/s}$" and "factor of 2" in own["why"]
    assert script.mistake(db, "s1", "position")["own"] is False                 # a mistake on one concept is not carried to another


def test_the_closing_question_is_one_the_student_has_not_met(db):
    from pramana.assess import session

    first = script.check_question(db, "s1", "velocity")
    assert first["type"] == "mcq" and first["concept_id"] == "velocity"
    assert script.check_question(db, "s1", "velocity", avoid={first["id"]})["id"] != first["id"]
    sitting = session.start(db, "s1", "quiz", ["velocity"], n=1, types=["mcq"])
    session.answer(db, "course", sitting["assessment_id"], sitting["question"]["id"], 1)
    assert script.check_question(db, "s1", "velocity")["id"] != sitting["question"]["id"]


def test_a_card_builds_up_as_it_is_spoken():
    draw = render.panel([{"text": "FROM YOUR OWN PRACTICE", "face": "mono", "size": 23, "colour": render.CITE},
                         {"text": r"Find $a$ if $F = 12\ \text{N}$ and $m = 3\ \text{kg}$.", "size": 31},
                         {"text": r"$8\ \text{m/s}^{2}$", "size": 31, "colour": render.BAD, "lead": "YOU ANSWERED", "at": 1.0},
                         {"text": r"$4\ \text{m/s}^{2}$", "size": 31, "colour": render.GOOD, "lead": "CORRECT", "at": 2.0}])
    lit = lambda t: int(np.asarray(draw(t)).astype(int).sum())                  # noqa: E731
    assert lit(0.5) < lit(1.6) < lit(2.6)                                       # each line arrives when its time comes
    assert lit(2.6) == lit(9.0) and draw(0.0).size == (render.W, render.H)
