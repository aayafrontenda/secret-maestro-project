import pytest

from app.services.scoring import CriterionSpec, ScoringError, normalize_answer, score

# The default Freedom Broker checklist (weights sum to 100).
SPECS = [
    CriterionSpec("c1", "Contact", "yes_no", weight=10, section="Start", position=1),
    CriterionSpec("c2", "Need", "yes_no", weight=15, allow_na=True, section="Start", position=2),
    CriterionSpec("c3", "ID", "yes_no", weight=20, allow_na=True, section="Safety", position=3),
    CriterionSpec(
        "c4",
        "Consult",
        "scale",
        weight=20,
        allow_na=True,
        section="Safety",
        scale_max=20,
        scale_steps=(20, 15, 10, 5, 0),
        position=4,
    ),
    CriterionSpec("c5", "Empathy", "yes_no", weight=15, section="Flow", position=5),
    CriterionSpec(
        "c6",
        "Dialog",
        "scale",
        weight=15,
        section="Flow",
        scale_max=10,
        scale_steps=(10, 7, 4, 0),
        position=6,
    ),
    CriterionSpec("c7", "Closing", "yes_no", weight=5, allow_na=True, section="Flow", position=7),
    CriterionSpec("c8", "Grave", "yes_no", weight=0, is_flag=True, position=8),
]


def all_yes() -> dict:
    return {
        "c1": "yes",
        "c2": "yes",
        "c3": "yes",
        "c4": 20,
        "c5": "yes",
        "c6": 10,
        "c7": "yes",
        "c8": "no",
    }


def test_perfect_score_is_100():
    r = score(SPECS, all_yes())
    assert r.total == 100.0
    assert r.grave_error is False
    assert [c.points for c in r.criteria] == [10, 15, 20, 20, 15, 15, 5, None]


def test_all_no_is_zero_not_none():
    answers = {
        "c1": "no",
        "c2": "no",
        "c3": "no",
        "c4": 0,
        "c5": "no",
        "c6": 0,
        "c7": "no",
        "c8": "no",
    }
    r = score(SPECS, answers)
    assert r.total == 0.0


def test_scale_is_proportional_to_weight():
    a = all_yes()
    a["c4"] = 15  # 15/20 of 20 pts = 15
    a["c6"] = 7  # 7/10 of 15 pts = 10.5
    r = score(SPECS, a)
    by = {c.code: c for c in r.criteria}
    assert by["c4"].points == 15.0
    assert by["c6"].points == 10.5
    assert r.total == 90.5


def test_na_redistributes_weight_so_max_stays_100():
    a = all_yes()
    a["c3"] = "na"  # drop 20 of weight; remaining 80 scales by 1.25
    r = score(SPECS, a)
    assert r.total == 100.0
    by = {c.code: c for c in r.criteria}
    assert by["c3"].applicable is False
    assert by["c3"].points is None
    assert by["c1"].effective_weight == 12.5
    assert by["c7"].effective_weight == 6.25


def test_na_redistribution_with_partial_answers():
    # c3 N/A, c1 No -> lose 10 of 80 applicable weight -> 70/80 * 100 = 87.5
    a = all_yes()
    a["c3"] = "na"
    a["c1"] = "no"
    r = score(SPECS, a)
    assert r.total == 87.5


def test_rounding_to_two_decimals():
    # c2 N/A (15 off) -> scale = 100/85. c1 yes -> 10 * 100/85 = 11.7647 -> 11.76 per criterion
    a = all_yes()
    a["c2"] = "na"
    a["c3"] = "no"
    a["c4"] = 0
    a["c5"] = "no"
    a["c6"] = 0
    a["c7"] = "no"
    r = score(SPECS, a)
    assert r.total == 11.76
    by = {c.code: c for c in r.criteria}
    assert by["c1"].points == 11.76


def test_grave_error_is_separate_flag_and_does_not_affect_total():
    a = all_yes()
    a["c8"] = "yes"
    r = score(SPECS, a)
    assert r.total == 100.0
    assert r.grave_error is True
    assert r.flags == {"c8": True}


def test_sections_are_summed():
    a = all_yes()
    a["c3"] = "no"
    r = score(SPECS, a)
    sections = {s.name: s for s in r.sections}
    assert sections["Start"].points == 25.0 and sections["Start"].max_points == 25.0
    assert sections["Safety"].points == 20.0 and sections["Safety"].max_points == 40.0
    assert sections["Flow"].points == 35.0
    assert "c8" not in sum((s.criteria for s in r.sections), [])


def test_all_na_gives_no_total():
    specs = [
        CriterionSpec("a", "A", "yes_no", weight=50, allow_na=True),
        CriterionSpec("b", "B", "yes_no", weight=50, allow_na=True),
    ]
    r = score(specs, {"a": "na", "b": "na"})
    assert r.total is None
    assert r.max_total == 0.0


def test_na_where_not_allowed_is_coerced_to_no_with_note():
    a = all_yes()
    a["c1"] = "na"
    r = score(SPECS, a)
    by = {c.code: c for c in r.criteria}
    assert by["c1"].answer == "no"
    assert by["c1"].normalization_note
    assert r.total == 90.0


def test_scale_answer_snaps_to_nearest_step_and_clamps():
    spec = SPECS[3]  # c4, steps 20/15/10/5/0
    assert normalize_answer(spec, 17) == (15, "scale answer 17.0 snapped to nearest step 15")
    assert normalize_answer(spec, 18) == (20, "scale answer 18.0 snapped to nearest step 20")
    assert normalize_answer(spec, 25)[0] == 20
    assert normalize_answer(spec, -3)[0] == 0
    assert normalize_answer(spec, "15") == (15, None)


def test_textual_yes_no_variants():
    spec = SPECS[0]
    assert normalize_answer(spec, "Да")[0] == "yes"
    assert normalize_answer(spec, "НЕТ")[0] == "no"
    assert normalize_answer(spec, True)[0] == "yes"
    assert normalize_answer(SPECS[1], "N/A")[0] == "na"


def test_weights_not_summing_to_100_are_normalised():
    specs = [
        CriterionSpec("a", "A", "yes_no", weight=3),
        CriterionSpec("b", "B", "yes_no", weight=1),
    ]
    r = score(specs, {"a": "yes", "b": "no"})
    assert r.total == 75.0


def test_missing_answer_raises():
    with pytest.raises(ScoringError, match="missing answers"):
        score(SPECS, {"c1": "yes"})


def test_invalid_answer_raises():
    with pytest.raises(ScoringError):
        score(SPECS, {**all_yes(), "c1": "maybe"})
    with pytest.raises(ScoringError):
        score(SPECS, {**all_yes(), "c4": "high"})


def test_spec_from_dict_parses_steps():
    spec = CriterionSpec.from_dict(
        {
            "code": "x",
            "title": "X",
            "answer_type": "scale",
            "weight": 10,
            "scale_max": 10,
            "scale_steps": [{"value": 10, "label": "a"}, {"value": 4, "label": "b"}, 0],
        }
    )
    assert spec.scale_steps == (10, 4, 0)
