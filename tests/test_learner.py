from pramana.learner import DAY, PRIOR, Learner, decayed, days_until, guess, posterior, predict_correct, slip
from pramana.db import now


def test_correct_answer_raises_belief_and_wrong_lowers_it():
    assert posterior(0.4, 1.0, 0.25, slip(2)) > 0.4
    assert posterior(0.4, 0.0, 0.25, slip(2)) < 0.4


def test_a_hard_numeric_answer_is_stronger_evidence_than_an_easy_mcq():
    easy_mcq = posterior(0.3, 1.0, guess("mcq", 1), slip(1))
    hard_numeric = posterior(0.3, 1.0, guess("numeric", 4), slip(4))
    assert hard_numeric > easy_mcq + 0.3
    assert guess("mcq", 1) > guess("mcq", 4) > guess("numeric", 4)


def test_partial_credit_sits_between_right_and_wrong():
    right, wrong = posterior(0.5, 1.0, 0.05, 0.1), posterior(0.5, 0.0, 0.05, 0.1)
    assert wrong < posterior(0.5, 0.5, 0.05, 0.1) < right


def test_forgetting_decays_towards_a_floor_and_practice_slows_it():
    assert decayed(0.9, 0, 0) == 0.9
    week_once = decayed(0.9, 7 * DAY, 0)
    week_practised = decayed(0.9, 7 * DAY, 4)
    assert 0.1 < week_once < week_practised < 0.9
    assert decayed(0.9, 400 * DAY, 0) < 0.11


def test_days_until_is_consistent_with_decay():
    days = days_until(0.9, 2, 0.6)
    assert abs(decayed(0.9, days * DAY, 2) - 0.6) < 1e-6
    assert days_until(0.5, 0, 0.6) is None


def test_new_student_starts_at_the_prior(db):
    state = Learner(db, "s1").state()
    assert {s.current for s in state.values()} == {PRIOR}
    assert all(s.level == "unknown" for s in state.values())


def test_success_lifts_prerequisites_and_failure_caps_dependants(db):
    learner = Learner(db, "s1")
    learner.observe("velocity", 1.0, "numeric", 3)
    state = learner.state()
    assert state["velocity"].current > PRIOR
    assert state["position"].current > PRIOR          # credited: velocity rests on it
    assert state["acceleration"].current == PRIOR     # nothing learned about what comes after

    learner = Learner(db, "s1")
    db.insert("students", {"id": "s2", "name": "Two", "created": now(), "profile": {}})
    other = Learner(db, "s2")
    before, after = other.observe("position", 0.0, "mcq", 1)
    state = other.state()
    assert after < before
    assert state["velocity"].current <= after + 0.15 + 1e-9
    assert state["acceleration"].current <= after + 0.15 + 1e-9


def test_every_update_is_logged_with_before_and_after(db):
    learner = Learner(db, "s1")
    learner.observe("position", 1.0, "mcq", 2, detail={"question_id": "q"})
    rows = db.all("SELECT * FROM evidence WHERE student_id = 's1' AND concept_id = 'position'")
    assert len(rows) == 1 and rows[0]["p_after"] > rows[0]["p_before"] and rows[0]["detail"]["question_id"] == "q"


def test_chat_evidence_moves_belief_less_than_a_quiz_answer(db):
    quiz = Learner(db, "s1")
    _, after_quiz = quiz.observe("position", 1.0, "short", 2, source="quiz")
    db.insert("students", {"id": "s3", "name": "Three", "created": now(), "profile": {}})
    _, after_chat = Learner(db, "s3").observe("position", 1.0, "chat", 2, source="chat", weight=0.35)
    assert PRIOR < after_chat < after_quiz


def test_readiness_and_root_cause(db):
    learner = Learner(db, "s1")
    learner.observe("position", 0.0, "numeric", 1)
    state = learner.state()
    assert learner.readiness("velocity", state) < 1.0
    assert learner.weakest_prerequisite("acceleration", state) == "position"


def test_prediction_grows_with_mastery_and_falls_with_difficulty():
    assert predict_correct(0.9, "numeric", 2) > predict_correct(0.2, "numeric", 2)
    assert predict_correct(0.9, "numeric", 1) > predict_correct(0.9, "numeric", 5)


def test_an_unassessed_student_has_no_named_prerequisite_gap(db):
    learner = Learner(db, "s1")
    assert learner.weakest_prerequisite("acceleration", learner.state()) is None
