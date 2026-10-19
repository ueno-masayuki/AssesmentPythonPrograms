"""学生向けフィードバック文の組み立てと、Moodle一括アップロード用zipの生成。"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from .config import Assignment

if TYPE_CHECKING:
    from .pipeline import StudentResult


def build_feedback_text(assignment: Assignment, res: "StudentResult") -> str:
    """フィードバックファイル（Markdown）の全文を組み立てる。"""
    lines: list[str] = [f"# {assignment.title} — フィードバック", ""]
    lines.append(f"**{res.submission.student_name}** さん")
    lines.append("")
    lines.append(f"## 評点: {res.score.final_grade:g} / {res.score.max_grade:g}")
    lines.append("")

    if not res.submission.has_code:
        lines.append("採点可能なPythonファイル（.py）が見つかりませんでした。")
        lines.append("提出形式を確認して、再提出してください。")
        return "\n".join(lines) + "\n"

    if res.outcome is not None and res.outcome.results:
        lines.append("## 自動テストの結果")
        lines.append("")
        lines.append("| テスト | 結果 | 備考 |")
        lines.append("|---|---|---|")
        for r in res.outcome.results:
            mark = "✅ 合格" if r.passed else {"wrong_output": "❌ 出力不一致",
                                               "error": "⚠️ 実行エラー",
                                               "timeout": "⏱️ 時間切れ"}.get(r.status, "❌ 不合格")
            note = (r.detail or "").replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {r.case.name} | {mark} | {note[:120]} |")
        lines.append("")

    if res.evaluation is not None:
        if res.evaluation.criteria:
            points = {r.id: r for r in assignment.rubric}
            lines.append("## 観点別評価")
            lines.append("")
            lines.append("| 観点 | 得点 | コメント |")
            lines.append("|---|---|---|")
            for c in res.evaluation.criteria:
                crit = points.get(c.criterion_id)
                name = crit.name if crit else c.criterion_id
                maxp = f"{crit.points:g}" if crit else "?"
                reason = c.reason_ja.replace("|", "\\|").replace("\n", " ")
                lines.append(f"| {name} | {c.score:g} / {maxp} | {reason} |")
            lines.append("")
        lines.append("## 講評")
        lines.append("")
        lines.append(res.evaluation.feedback_ja.strip())
        lines.append("")
    else:
        lines.append("## 講評")
        lines.append("")
        lines.append("（この採点では自動テストの結果のみで評価しています）")
        lines.append("")

    return "\n".join(lines) + "\n"


def build_csv_comment(assignment: Assignment, res: "StudentResult") -> str:
    """ワークシートCSVの「フィードバックコメント」用の短縮版（MoodleはHTML表示）。"""
    parts: list[str] = []
    if res.outcome is not None and res.outcome.results:
        parts.append(f"自動テスト: {res.outcome.passed_count}/{len(res.outcome.results)} 件合格")
    if res.evaluation is not None:
        parts.append(res.evaluation.overall_comment_ja.strip())
    elif not res.submission.has_code:
        parts.append("採点可能なPythonファイルが見つかりませんでした。提出形式を確認してください。")
    parts.append("詳細はフィードバックファイルを確認してください。")
    return "<br>".join(p for p in parts if p)


def write_feedback_zip(zip_path: Path, assignment: Assignment, results: list["StudentResult"]) -> None:
    """Moodleの「複数のフィードバックファイルをzipでアップロード」形式のzipを作る。

    フォルダ名は提出時のフォルダ名をそのまま使う（Moodleは参加者IDで照合する）。
    """
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for res in results:
            text = build_feedback_text(assignment, res)
            zf.writestr(f"{res.submission.folder_name}/{assignment.feedback_filename}", text)
