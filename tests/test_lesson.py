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
