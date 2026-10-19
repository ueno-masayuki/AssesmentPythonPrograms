"""採点の一連の処理。WebUIのジョブとCLIの両方からこのモジュールを呼ぶ。"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import feedback as feedback_mod
from . import llm as llm_mod
from . import report as report_mod
from .config import Assignment
from .runner import RunOutcome, run_tests
from .scoring import ScoreBreakdown, compute_score
from .submissions import Submission, discover_submissions
from .worksheet import Worksheet, load_worksheet

ProgressFn = Callable[[int, int, str], None]


@dataclass
class StudentResult:
    submission: Submission
    outcome: RunOutcome | None
    evaluation: llm_mod.LLMEvaluation | None
    score: ScoreBreakdown
    matched_worksheet: bool = True
    llm_error: str | None = None

    def flags(self) -> list[str]:
        flags = list(self.submission.flags)
        if not self.matched_worksheet:
            flags.append("ワークシートに対応する行が見つかりません（評点は手動で登録してください）")
        if self.llm_error:
            flags.append(f"LLM評価に失敗（テストのみで採点）: {self.llm_error}")
        if self.outcome:
            if any(r.status == "timeout" for r in self.outcome.results):
                flags.append("タイムアウトしたテストがあります")
            if any(r.status == "error" for r in self.outcome.results):
                flags.append("実行時エラーのテストがあります")
        return flags


@dataclass
class GradeRun:
    assignment: Assignment
    results: list[StudentResult]
    max_grade: float
    llm_used: bool
    timestamp: str
    warnings: list[str] = field(default_factory=list)
    unmatched_worksheet_rows: list[str] = field(default_factory=list)
    outputs: dict[str, Path] = field(default_factory=dict)


def grade(
    assignment: Assignment,
    submissions_path: Path,
    out_dir: Path,
    worksheet_path: Path | None = None,
    use_llm: bool = True,
    use_cache: bool = True,
    progress: ProgressFn | None = None,
) -> GradeRun:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    warnings: list[str] = []

    # --- 採点可能かの検査 -------------------------------------------------
    if assignment.rubric:
        unassigned = [t.name for t in assignment.tests if not t.criterion]
        if unassigned:
            raise ValueError(
                "次のテストケースに評価基準（ルーブリック）が割り当てられていません: "
                + ", ".join(unassigned)
            )
    llm_usable = (use_llm and assignment.llm_enabled and bool(assignment.llm_criteria)
                  and llm_mod.llm_available())
    if not assignment.tests and not llm_usable:
        raise ValueError(
            "採点できません。課題にテストケースを登録するか、"
            "ルーブリックを登録して LLM評価（ANTHROPIC_API_KEY）を有効にしてください。"
        )

    # --- 入力の読み込み --------------------------------------------------
    worksheet: Worksheet | None = None
    if worksheet_path is not None:
        worksheet = load_worksheet(worksheet_path)

    max_grade = (worksheet.max_grade if worksheet and worksheet.max_grade
                 else assignment.max_grade)
    if max_grade is None:
        raise ValueError("最大評点が決まりません。ワークシートか課題設定の max_grade を指定してください。")

    subs = discover_submissions(submissions_path, out_dir, assignment.expected_filename)

    # --- LLMの利用可否 ---------------------------------------------------
    llm_enabled = use_llm and assignment.llm_enabled and bool(assignment.llm_criteria)
    if llm_enabled and not llm_mod.llm_available():
        warnings.append(
            "ANTHROPIC_API_KEY が未設定のため、AI評価対象の基準を除外し、"
            "テスト基準の得点率から評点を換算しました。"
        )
        llm_enabled = False
    cache_dir = out_dir / ".cache"

    # --- 学生ごとの採点 ---------------------------------------------------
    results: list[StudentResult] = []
    total = len(subs)
    llm_used_any = False
    for i, sub in enumerate(subs):
        if progress:
            progress(i, total, sub.student_name)

        outcome: RunOutcome | None = None
        evaluation = None
        llm_error = None
        if sub.has_code:
            if assignment.tests:
                outcome = run_tests(sub.code_text, assignment,
                                    filename=assignment.expected_filename or "main.py")
            if llm_enabled:
                try:
                    evaluation = llm_mod.evaluate(assignment, sub.code_text, outcome,
                                                  cache_dir=cache_dir, use_cache=use_cache)
                    llm_used_any = True
                except llm_mod.LLMUnavailable as e:
                    llm_error = str(e)

        score = compute_score(assignment, outcome, evaluation, max_grade)
        if not sub.has_code:
            score.final_grade = 0.0

        results.append(StudentResult(
            submission=sub, outcome=outcome, evaluation=evaluation,
            score=score, llm_error=llm_error,
        ))

    if progress:
        progress(total, total, "出力を書き出し中")

    run = GradeRun(
        assignment=assignment, results=results, max_grade=max_grade,
        llm_used=llm_used_any, timestamp=timestamp, warnings=warnings,
    )

    # --- 出力 -------------------------------------------------------------
    _write_outputs(run, worksheet, out_dir)
    return run


def _write_outputs(run: GradeRun, worksheet: Worksheet | None, out_dir: Path) -> None:
    a = run.assignment

    # 詳細ログ（監査用）
    details_dir = out_dir / "details"
    for res in run.results:
        d = details_dir / res.submission.folder_name
        d.mkdir(parents=True, exist_ok=True)
        log_lines = [f"学生: {res.submission.student_name} ({res.submission.participant_id})",
                     f"採点対象: {res.submission.code_path}",
                     f"評点: {res.score.final_grade:g} / {res.score.max_grade:g}", ""]
        if res.outcome:
            for r in res.outcome.results:
                log_lines += [f"[{r.status}] {r.case.name}",
                              f"  stdout: {r.stdout!r}" if r.stdout else "",
                              f"  stderr: {r.stderr!r}" if r.stderr else "",
                              f"  detail: {r.detail}" if r.detail else ""]
        (d / "test_log.txt").write_text("\n".join(l for l in log_lines if l != ""), encoding="utf-8")

    # ワークシートCSV
    if worksheet is not None:
        matched_rows = set()
        for res in run.results:
            row = worksheet.find_row(res.submission.participant_id, res.submission.student_name)
            if row is None:
                res.matched_worksheet = False
                continue
            matched_rows.add(id(row))
            comment = feedback_mod.build_csv_comment(a, res)
            worksheet.set_grade(row, res.score.final_grade, comment)
        run.unmatched_worksheet_rows = [
            worksheet.fullname(row) or (row[worksheet.columns["identifier"]] if row else "?")
            for row in worksheet.rows if id(row) not in matched_rows
        ]
        csv_path = out_dir / "grading_worksheet_filled.csv"
        worksheet.write(csv_path)
        run.outputs["worksheet"] = csv_path

    # フィードバックzip
    zip_path = out_dir / "feedback_files.zip"
    feedback_mod.write_feedback_zip(zip_path, a, run.results)
    run.outputs["feedback_zip"] = zip_path

    # レポート
    report_path = out_dir / "report.md"
    report_path.write_text(report_mod.build_report(run), encoding="utf-8")
    run.outputs["report"] = report_path


def check_model_answer(assignment: Assignment) -> RunOutcome:
    """回答例に対して全テストを実行する（設定の妥当性確認）。"""
    if not assignment.model_answer.strip():
        raise ValueError("回答例（model_answer）が登録されていません")
    if not assignment.tests:
        raise ValueError("テストケースが定義されていません")
    return run_tests(assignment.model_answer, assignment,
                     filename=assignment.expected_filename or "main.py")
