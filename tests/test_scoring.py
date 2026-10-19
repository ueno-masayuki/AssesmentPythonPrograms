from pygrader.config import Assignment, RubricCriterion, TestCase
from pygrader.llm import CriterionScore, LLMEvaluation
from pygrader.runner import RunOutcome, TestResult
from pygrader.scoring import compute_score, round_half_up


def _assignment():
    t1 = TestCase(name="t1", criterion="correctness", stdin="", expected_stdout="y", weight=2)
    t2 = TestCase(name="t2", criterion="correctness", stdin="", expected_stdout="y", weight=1)
    return Assignment(
        title="t",
        max_grade=100.0,
        tests=[t1, t2],
        rubric=[
            RubricCriterion(id="correctness", name="動作", points=70),
            RubricCriterion(id="readability", name="可読性", points=30),
        ],
    )


def _outcome(a: Assignment, passed: list[bool]) -> RunOutcome:
    return RunOutcome(results=[
        TestResult(case=t, status="pass" if ok else "wrong_output")
        for t, ok in zip(a.tests, passed)
    ])


def _evaluation(score: float) -> LLMEvaluation:
    return LLMEvaluation(
        rubric_ratio=0.0,
        criteria=[CriterionScore(criterion_id="readability", score=score, reason_ja="理由")],
        feedback_ja="f", overall_comment_ja="o",
    )


def test_tests_fill_criterion_points():
    a = _assignment()
    # 重み2のテストだけ合格 → correctness = 70 × 2/3、readability = 30点満点中24点
    s = compute_score(a, _outcome(a, [True, False]), _evaluation(24.0), max_grade=100)
    by_id = {c.criterion.id: c for c in s.criteria}
    assert abs(by_id["correctness"].earned - 70 * 2 / 3) < 1e-9
    assert by_id["correctness"].source == "tests"
    assert by_id["readability"].earned == 24.0
    assert by_id["readability"].source == "llm"
    assert s.final_grade == round_half_up(70 * 2 / 3 + 24.0)
    assert not s.renormalized


def test_llm_score_clamped_to_points():
    a = _assignment()
    s = compute_score(a, _outcome(a, [True, True]), _evaluation(999.0), max_grade=100)
    by_id = {c.criterion.id: c for c in s.criteria}
    assert by_id["readability"].earned == 30.0  # 配点を超えない
    assert s.final_grade == 100.0


def test_no_llm_renormalizes_from_test_criteria():
    a = _assignment()
    # LLM評価なし: correctness 2/3 → 全体も 2/3 × 100
    s = compute_score(a, _outcome(a, [True, False]), None, max_grade=100)
    assert s.renormalized
    assert s.final_grade == round_half_up(100 * 2 / 3)


def test_worksheet_max_grade_scales():
    a = _assignment()
    # ルーブリック合計100だがワークシートの最大評点が50 → 比例換算
    s = compute_score(a, _outcome(a, [True, True]), _evaluation(30.0), max_grade=50)
    assert s.final_grade == 50.0
    s2 = compute_score(a, _outcome(a, [True, False]), None, max_grade=50)
    assert s2.final_grade == round_half_up(50 * 2 / 3)


def test_rubric_empty_tests_only():
    t = TestCase(name="t", stdin="", expected_stdout="y")
    a = Assignment(title="t", tests=[t], rubric=[])
    outcome = RunOutcome(results=[TestResult(case=t, status="pass")])
    s = compute_score(a, outcome, None, max_grade=40)
    assert s.final_grade == 40.0


def test_round_half_up():
    assert round_half_up(84.25, 1) == 84.3
    assert round_half_up(84.24, 1) == 84.2
    assert round_half_up(0.5, 0) == 1.0


def test_validate_points_must_match_max_grade():
    import pytest

    from pygrader.config import ConfigError

    a = _assignment()
    a.rubric[1].points = 20  # 合計90 ≠ 100
    with pytest.raises(ConfigError, match="配点合計"):
        a.validate()


def test_validate_unknown_criterion():
    import pytest

    from pygrader.config import ConfigError

    a = _assignment()
    a.tests[0].criterion = "nonexistent"
    with pytest.raises(ConfigError, match="nonexistent"):
        a.validate()