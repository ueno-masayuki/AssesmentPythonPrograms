from pygrader.config import Assignment, RubricCriterion, TestCase
from pygrader.scoring import compute_score, round_half_up


def _assignment(with_tests=True, with_rubric=True):
    return Assignment(
        title="t",
        tests=[TestCase(name="x", stdin="", expected_stdout="y")] if with_tests else [],
        rubric=[RubricCriterion(id="r", name="r", points=10)] if with_rubric else [],
        weight_tests=0.7,
        weight_rubric=0.3,
    )


def test_combined_score():
    s = compute_score(_assignment(), test_ratio=1.0, rubric_ratio=0.5, max_grade=100)
    assert s.final_grade == 85.0  # 0.7*1.0 + 0.3*0.5 = 0.85


def test_llm_missing_renormalizes_to_tests():
    s = compute_score(_assignment(), test_ratio=0.5, rubric_ratio=None, max_grade=100)
    assert s.final_grade == 50.0


def test_no_tests_rubric_only():
    s = compute_score(_assignment(with_tests=False), test_ratio=0.0, rubric_ratio=0.8, max_grade=50)
    assert s.final_grade == 40.0


def test_round_half_up():
    assert round_half_up(84.25, 1) == 84.3
    assert round_half_up(84.24, 1) == 84.2
    assert round_half_up(0.5, 0) == 1.0
