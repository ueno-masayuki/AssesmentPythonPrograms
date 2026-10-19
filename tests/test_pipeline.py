from pathlib import Path

from pygrader.config import TestCase
from pygrader.feedback import build_csv_comment, build_feedback_text
from pygrader.pipeline import classify_special, grade
from pygrader.runner import RunOutcome, TestResult


def _outcome(statuses: list[str]) -> RunOutcome:
    return RunOutcome(results=[
        TestResult(case=TestCase(name=f"t{i}", stdin="", expected_stdout="y"), status=s)
        for i, s in enumerate(statuses)
    ])


def test_classify_syntax_error():
    special, note = classify_special("def f(:\n", None)
    assert special == "not_runnable"
    assert "構文エラー" in note


def test_classify_all_errors():
    special, _ = classify_special("print(1)\n", _outcome(["error", "error"]))
    assert special == "not_runnable"


def test_classify_io_mismatch():
    special, _ = classify_special("print(1)\n", _outcome(["wrong_output", "wrong_output"]))
    assert special == "io_mismatch"
    # 出力不一致 + 実行エラー混在（関数未定義など）も入出力不適合として扱う
    special, _ = classify_special("print(1)\n", _outcome(["wrong_output", "error"]))
    assert special == "io_mismatch"


def test_classify_normal_cases():
    assert classify_special("print(1)\n", _outcome(["pass", "wrong_output"]))[0] is None
    assert classify_special("print(1)\n", _outcome(["timeout", "timeout"]))[0] is None
    assert classify_special("print(1)\n", None)[0] is None


def test_grade_marks_special_cases(sample_assignment, fixtures: Path, tmp_path: Path):
    run = grade(sample_assignment, fixtures / "submissions.zip", tmp_path / "out",
                worksheet_path=fixtures / "worksheet_ja.csv", use_llm=False)
    by_id = {r.submission.participant_id: r for r in run.results}

    # 佐藤: NameErrorで全テストエラー → 実行不能・評点0
    sato = by_id["100003"]
    assert sato.special == "not_runnable"
    assert sato.score.final_grade == 0.0
    fb = build_feedback_text(sample_assignment, sato)
    assert "エラーで実行できません" in fb
    assert "評点: 0" in fb
    assert "エラー" in build_csv_comment(sample_assignment, sato)

    # 鈴木: 一部合格 → 特別ケースではない
    suzuki = by_id["100002"]
    assert suzuki.special is None
    assert suzuki.score.final_grade > 0

    # 田中: 無限ループ（全タイムアウト）→ 特別ケースではないが0点
    tanaka = by_id["100004"]
    assert tanaka.special is None
    assert tanaka.score.final_grade == 0.0


def test_io_mismatch_feedback_text(sample_assignment):
    from pygrader.pipeline import StudentResult
    from pygrader.scoring import compute_score
    from pygrader.submissions import Submission

    sub = Submission(student_name="テスト 学生", participant_id="1",
                     folder_name="テスト 学生_1_assignsubmission_file_",
                     folder_path=Path("."), code_path=Path("a.py"), code_text="print(1)")
    outcome = RunOutcome(results=[
        TestResult(case=t, status="wrong_output") for t in sample_assignment.tests
    ])
    res = StudentResult(
        submission=sub, outcome=outcome, evaluation=None,
        score=compute_score(sample_assignment, outcome, None, 100),
        special="io_mismatch",
    )
    res.score.final_grade = 0.0
    fb = build_feedback_text(sample_assignment, res)
    assert "問題文" in fb
    assert "評点: 0" in fb
    assert "観点別評価" not in fb  # 特別ケースではルーブリック表を出さない
    assert "問題文" in build_csv_comment(sample_assignment, res)
