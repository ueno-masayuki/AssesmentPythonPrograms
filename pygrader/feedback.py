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

    if res.special == "not_runnable":
        lines.append("提出されたプログラムはエラーで実行できませんでした。")
        if res.special_note:
            lines.append("")
            lines.append(f"> {res.special_note}")
        lines.append("")
        lines.append("まず手元の環境でプログラムを実行し、エラーなく動作することを確認してから")
        lines.append("提出してください。エラーメッセージをよく読むと、原因の行番号や種類が分かります。")
        lines.extend(_test_table(res))
        return "\n".join(lines) + "\n"

    if res.special == "io_mismatch":
        lines.append("プログラムは実行できましたが、入力の受け取り方または出力の形式が")
        lines.append("問題文の指定と一致していないため、すべてのテストが不合格になりました。")
        lines.append("")
        lines.append("**問題文をもう一度よく読み**、入力の形式（行数・区切り）と出力の形式")
        lines.append("（文言・空白・改行・小数の表記など）を正確に合わせてから再提出してください。")
        lines.extend(_test_table(res))
        return "\n".join(lines) + "\n"

    lines.extend(_test_table(res))

    if res.score.criteria:
        lines.append("## 観点別評価")
        lines.append("")
        lines.append("| 観点 | 得点 | 評価方法 | コメント |")
        lines.append("|---|---|---|---|")
        for c in res.score.criteria:
            if c.source == "none":
                continue
            method = "自動テスト" if c.source == "tests" else "AI評価"
            note = c.note.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {c.criterion.name} | {_fmt(c.earned)} / {c.criterion.points:g} "
                         f"| {method} | {note} |")
        lines.append("")
        if res.score.renormalized:
            lines.append("※ AI評価を行わなかったため、自動テストで評価できる観点の得点率から"
                         "評点を換算しています。")
            lines.append("")

    if res.evaluation is not None:
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


def _fmt(value: float) -> str:
    from .scoring import round_half_up

    return f"{round_half_up(value):g}"


def _test_table(res: "StudentResult") -> list[str]:
    if res.outcome is None or not res.outcome.results:
        return []
    lines = ["", "## 自動テストの結果", "", "| テスト | 結果 | 備考 |", "|---|---|---|"]
    for r in res.outcome.results:
        mark = "✅ 合格" if r.passed else {"wrong_output": "❌ 出力不一致",
                                           "error": "⚠️ 実行エラー",
                                           "timeout": "⏱️ 時間切れ"}.get(r.status, "❌ 不合格")
        note = (r.detail or "").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r.case.name} | {mark} | {note[:120]} |")
    lines.append("")
    return lines


def build_csv_comment(assignment: Assignment, res: "StudentResult") -> str:
    """ワークシートCSVの「フィードバックコメント」用の短縮版（MoodleはHTML表示）。"""
    parts: list[str] = []
    if not res.submission.has_code:
        parts.append("採点可能なPythonファイルが見つかりませんでした。提出形式を確認してください。")
    elif res.special == "not_runnable":
        parts.append("プログラムがエラーで実行できませんでした。手元で実行確認のうえ再提出してください。")
    elif res.special == "io_mismatch":
        parts.append("入力・出力の形式が問題文の指定と一致していません。問題文を再確認してください。")
    else:
        breakdown = res.score.breakdown_text()
        if breakdown:
            parts.append(f"内訳: {breakdown}")
        elif res.outcome is not None and res.outcome.results:
            parts.append(f"自動テスト: {res.outcome.passed_count}/{len(res.outcome.results)} 件合格")
        if res.evaluation is not None:
            parts.append(res.evaluation.overall_comment_ja.strip())
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
