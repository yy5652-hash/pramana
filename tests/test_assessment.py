import pytest

from pramana.assess import numeric, session
from pramana.assess.grade import grade
from pramana.assess.select import Selector
from pramana.learner import Learner


def test_formula_evaluator_computes_and_refuses_code():
    assert numeric.evaluate("v0 + a*t", {"v0": 2.5, "a": 2, "t": 5}) == 12.5
    assert numeric.evaluate("sqrt(2*g*h)", {"h": 5}) == pytest.approx(9.899, abs=1e-3)
    assert numeric.evaluate("m*g*sin(radians(theta))", {"m": 2, "theta": 30}) == pytest.approx(9.8)
    for hostile in ("__import__('os').system('ls')", "open('x')", "v0.real", "[1,2][0]", "lambda: 1"):
        with pytest.raises(numeric.FormulaError):
            numeric.evaluate(hostile, {"v0": 1})
    with pytest.raises(numeric.FormulaError):
        numeric.evaluate("1/x", {"x": 0})


def test_student_numbers_are_parsed_in_common_notations():
    assert numeric.parse_number("12.5 m/s") == 12.5
    assert numeric.parse_number("about −3") == -3
    assert numeric.parse_number("1,200 N") == 1200
    assert numeric.parse_number("4.0 x 10^3 J") == 4000
    assert numeric.parse_number("no idea") is None


def test_wrong_numbers_are_diagnosed_by_their_signature():
    assert "sign" in numeric.diagnose(-10, 10, 2)
    assert "3.6" in numeric.diagnose(36, 10, 2, "m/s")
    assert numeric.diagnose(36, 10, 2, "s") == ""               # a time cannot be a km/h slip
    assert "60" in numeric.diagnose(600, 10, 2, "s")
    assert "9.8" in numeric.diagnose(98, 10, 2, "N")
    assert "1000" in numeric.diagnose(0.01, 10, 2)
    assert numeric.diagnose(7.3, 10, 2) == ""


def test_grading_mcq_reports_the_misconception_behind_a_distractor(db):
    question = db.one("SELECT * FROM questions WHERE id = 'q-position-1-mcq'")
    assert grade(question, 1)["score"] == 1.0
    wrong = grade(question, 0)
    assert wrong["score"] == 0.0 and wrong["misconception"] == "confuses speed with velocity"


def test_grading_numeric_uses_tolerance(db):
    question = db.one("SELECT * FROM questions WHERE id = 'q-velocity-2-numeric'")
    assert grade(question, "10.1 m/s")["score"] == 1.0
    assert grade(question, "11")["score"] == 0.0
    assert "sign" in grade(question, "-10")["misconception"]


def test_selector_never_repeats_a_question(db):
    selector = Selector(db, "s1")
    taken = []
    for _ in range(24):   # the whole bank
        question = selector.next_question(["position", "velocity", "acceleration"], taken)
        assert question and question["id"] not in taken
        taken.append(question["id"])
        db.insert("attempts", {"assessment_id": None, "student_id": "s1", "question_id": question["id"], "ts": 0.0,
                               "response": {"value": 1}, "score": 1.0, "feedback": {}})
    assert selector.next_question(["position", "velocity", "acceleration"], taken) is None


def test_selector_does_not_drill_a_concept_whose_prerequisite_just_failed(db):
    learner = Learner(db, "s1")
    for _ in range(2):
        learner.observe("position", 0.0, "numeric", 1)
    question = Selector(db, "s1").next_question(["position", "velocity", "acceleration"], [])
    assert question["concept_id"] == "position"


def test_selector_matches_difficulty_to_mastery(db):
    learner = Learner(db, "s1")
    for _ in range(6):
        learner.observe("position", 1.0, "numeric", 4)
    strong = Selector(db, "s1").next_question(["position"], [])
    weak = Selector(db, "s1").next_question(["acceleration"], [])
    assert strong["difficulty"] > weak["difficulty"]


def test_quiz_flow_updates_mastery_and_reports_weak_topics(db):
    started = session.start(db, "s1", "quiz", ["position", "velocity"], n=4)
    question = started["question"]
    assert "answer" not in question and "explanation" not in question
    seen = set()
    result = None
    while question:
        assert question["id"] not in seen
        seen.add(question["id"])
        result = session.answer(db, "course", started["assessment_id"], question["id"], 0 if question["type"] == "mcq" else "999")
        assert result["feedback"]["citations"][0]["locator"]["page"] >= 1
        assert result["feedback"]["mastery_after"] <= result["feedback"]["mastery_before"]
        question = result["next"]
    report = result["report"]
    assert report["score"]["possible"] == 4 and report["score"]["earned"] == 0
    assert report["weak_topics"] and report["weak_topics"][0]["study"]
    assert any("speed with velocity" in m["label"] for m in report["misconceptions"]) or all(r["type"] == "numeric" for r in report["review"])


def test_exam_covers_the_scope_evenly_and_withholds_feedback(db):
    started = session.start(db, "s1", "exam", None, n=6)
    assessment = db.one("SELECT * FROM assessments WHERE id = ?", [started["assessment_id"]])
    concepts = [db.one("SELECT concept_id FROM questions WHERE id = ?", [q])["concept_id"] for q in assessment["question_ids"]]
    assert sorted(concepts.count(c) for c in set(concepts)) == [2, 2, 2]
    result = session.answer(db, "course", started["assessment_id"], started["question"]["id"], 1)
    assert result["feedback"] == {"recorded": True}


def test_diagnostic_spreads_over_the_map(db):
    started = session.start(db, "s1", "diagnostic", n=3)
    question, concepts = started["question"], []
    while question:
        concepts.append(question["concept_id"])
        question = session.answer(db, "course", started["assessment_id"], question["id"], 1 if question["type"] == "mcq" else "10")["next"]
    assert len(set(concepts)) >= 2
