from pramana import schedule
from pramana.learner import DAY, Learner
from pramana.db import now


def test_new_student_plan_follows_prerequisite_order_and_ends_with_a_mock(db):
    plan = schedule.build(db, "course", "s1", days=6, minutes_per_day=60)
    learn = [item["concept_id"] for day in plan["days"] for item in day["items"] if item["kind"] == "learn"]
    assert learn == ["position", "velocity", "acceleration"]
    assert plan["days"][-1]["items"][-1]["kind"] == "mock"
    assert all(day["minutes"] <= 60 for day in plan["days"])
    assert all(item["why"] for day in plan["days"] for item in day["items"])


def test_learned_concepts_get_spaced_reviews(db):
    plan = schedule.build(db, "course", "s1", days=10, minutes_per_day=90)
    by_kind = [(day["day"], item["kind"], item["concept_id"]) for day in plan["days"] for item in day["items"]]
    first = min(d for d, kind, c in by_kind if kind == "learn" and c == "position")
    reviews = sorted(d for d, kind, c in by_kind if kind == "review" and c == "position")
    assert reviews == [first + 2, first + 5]


def test_what_does_not_fit_is_reported_not_dropped_silently(db):
    plan = schedule.build(db, "course", "s1", days=2, minutes_per_day=30)
    scheduled = sum(1 for day in plan["days"] for item in day["items"] if item["kind"] == "learn")
    assert scheduled == 1 and len(plan["unscheduled"]) >= 2


def test_a_mastered_concept_is_reviewed_before_the_forgetting_curve_drops_it(db):
    learner = Learner(db, "s1")
    start = now()
    for _ in range(5):
        learner.observe("position", 1.0, "numeric", 4, at=start)
    assert learner.state(start)["position"].level == "mastered"
    plan = schedule.build(db, "course", "s1", days=40, minutes_per_day=60, start=start)
    reviews = [day["day"] for day in plan["days"] for item in day["items"] if item["kind"] == "review" and item["concept_id"] == "position"]
    assert reviews, "a review should be scheduled before the exam"
    predicted = next(c for c in plan["without_review"] if c["concept_id"] == "position")
    assert predicted["on_exam_day"] < predicted["today"]
    # the review lands before mastery is predicted to fall under 60 %
    assert learner.state(start + (reviews[0] - 1) * DAY)["position"].current >= 0.6
