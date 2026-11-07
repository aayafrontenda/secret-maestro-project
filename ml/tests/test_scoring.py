import pytest

from maestro.scoring import InvalidAnswer, compute

ALL_YES = {"01": "yes", "02": "yes", "03": "yes", "04": 20, "05": "yes", "06": 10, "07": "yes"}


def test_all_top_answers_give_100():
    assert compute(ALL_YES).final_score == 100.0


def test_all_zero_answers_give_0():
    answers = {"01": "no", "02": "no", "03": "no", "04": 0, "05": "no", "06": 0, "07": "no"}
    assert compute(answers).final_score == 0.0


def test_na_redistribution_worked_example():
    answers = {"01": "yes", "02": "yes", "03": "na", "04": 15, "05": "yes", "06": 7, "07": "na"}
    result = compute(answers)
    assert result.applicable_weight == 75
    assert result.final_score == 87.33
    assert result.raw_points["06"] == 10.5
    assert result.points["03"] is None


def test_all_na_top_answers_still_reach_100():
    answers = {**ALL_YES, "02": "na", "03": "na", "04": "na", "07": "na"}
    assert compute(answers).final_score == 100.0


@pytest.mark.parametrize(("level", "points"), [(0, 70), (5, 75), (10, 80), (15, 85), (20, 90)])
def test_consultation_scale_steps(level, points):
    # 01 is "no", so 10 points are lost regardless of the consultation level.
    assert compute({**ALL_YES, "01": "no", "04": level}).final_score == points


@pytest.mark.parametrize(("level", "points"), [(0, 85), (4, 91), (7, 95.5), (10, 100)])
def test_dialogue_scale_steps(level, points):
    assert compute({**ALL_YES, "06": level}).final_score == points


def test_gross_violation_does_not_change_the_score():
    assert compute({**ALL_YES, "08": "yes"}).final_score == 100.0


@pytest.mark.parametrize(
    "bad",
    [
        {"04": 12},
        {"06": 5},
        {"06": True},
        {"01": "na"},
        {"05": "na"},
        {"06": "na"},
        {"08": "na"},
        {"02": "maybe"},
        {"99": "yes"},
    ],
)
def test_invalid_answers_are_rejected(bad):
    with pytest.raises(InvalidAnswer):
        compute({**ALL_YES, **bad})


def test_missing_answer_is_rejected():
    answers = dict(ALL_YES)
    del answers["03"]
    with pytest.raises(InvalidAnswer):
        compute(answers)
