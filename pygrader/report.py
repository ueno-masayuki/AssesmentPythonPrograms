"""教員向けMarkdownレポートの生成（統計・要確認一覧・類似提出の検出）。"""

from __future__ import annotations

import difflib
import io
import re
import statistics
import tokenize
from typing import TYPE_CHECKING

from .config import Assignment

if TYPE_CHECKING:
    from .pipeline import GradeRun, StudentResult

SIMILARITY_THRESHOLD = 0.9


def _strip_comments(code: str) -> str:
    """コメントと空白を取り除いた正規化ソース（類似度比較用）。"""
    try:
        tokens = tokenize.generate_tokens(io.StringIO(code).readline)
        parts = [t.string for t in tokens
                 if t.type not in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)]
        return " ".join(parts)
    except (tokenize.TokenizeError, SyntaxError, IndentationError):
        return re.sub(r"\s+", " ", re.sub(r"#.*", "", code))


def find_similar_pairs(results: list["StudentResult"]) -> list[tuple[str, str, float]]:
    coded = [(r.submission.student_name, _strip_comments(r.submission.code_text))
             for r in results if r.submission.has_code and r.submission.code_text.strip()]
    pairs: list[tuple[str, str, float]] = []
    for i in range(len(coded)):
        for j in range(i + 1, len(coded)):
            ratio = difflib.SequenceMatcher(None, coded[i][1], coded[j][1]).ratio()
            if ratio >= SIMILARITY_THRESHOLD:
                pairs.append((coded[i][0], coded[j][0], ratio))
    return sorted(pairs, key=lambda p: -p[2])


def _histogram(grades: list[float], max_grade: float) -> list[str]:
    bins = 10
    counts = [0] * bins
    for g in grades:
        idx = min(int(g / max_grade * bins), bins - 1) if max_grade > 0 else 0
        counts[idx] += 1
    width = max(counts) or 1
    lines = []
    for i, c in enumerate(counts):
        lo = int(i * max_grade / bins)
        hi = int((i + 1) * max_grade / bins)
        bar = "█" * round(c / width * 30)
        lines.append(f"{lo:>4}–{hi:<4} | {bar} {c}")
    return lines


def build_report(run: "GradeRun") -> str:
    a: Assignment = run.assignment
    results = run.results
    graded = [r for r in results if r.submission.has_code]
    grades = [r.score.final_grade for r in results]

    lines: list[str] = [f"# 採点レポート: {a.title}", ""]
    lines.append(f"- 実行日時: {run.timestamp}")
    lines.append(f"- 提出者数: {len(results)} 名（うち採点可能 {len(graded)} 名）")
    lines.append(f"- 最大評点: {run.max_grade:g}")
    lines.append(f"- LLM評価: {'あり（' + a.llm_model + '）' if run.llm_used else 'なし（テストのみで採点）'}")
    if run.warnings:
        lines.append("")
        lines.append("## ⚠️ 実行時の警告")
        lines.extend(f"- {w}" for w in run.warnings)
    lines.append("")

    if grades:
        lines.append("## 統計")
        lines.append("")
        lines.append(f"- 平均: {statistics.mean(grades):.1f} / 中央値: {statistics.median(grades):.1f}"
                     f" / 最高: {max(grades):g} / 最低: {min(grades):g}")
        lines.append("")
        lines.append("```")
        lines.extend(_histogram(grades, run.max_grade))
        lines.append("```")
        lines.append("")

    flagged = [r for r in results if r.flags()]
    if flagged:
        lines.append("## 要確認")
        lines.append("")
        for r in flagged:
            lines.append(f"- **{r.submission.student_name}** ({r.submission.participant_id}): "
                         + " / ".join(r.flags()))
        lines.append("")

    if a.similarity_check:
        pairs = find_similar_pairs(results)
        if pairs:
            lines.append("## 要確認: 類似提出")
            lines.append("")
            lines.append("コメント・空白を除いたソースの類似度が高いペアです（本格的な剽窃判定ではありません）。")
            lines.append("")
            for n1, n2, ratio in pairs:
                lines.append(f"- {n1} ↔ {n2}: 類似度 {ratio:.2f}")
            lines.append("")

    lines.append("## 学生別結果")
    lines.append("")
    lines.append("| 氏名 | 参加者ID | 評点 | テスト | ルーブリック | 備考 |")
    lines.append("|---|---|---|---|---|---|")
    for r in sorted(results, key=lambda x: x.submission.participant_id):
        tests = f"{r.outcome.passed_count}/{len(r.outcome.results)}" if r.outcome and r.outcome.results else "-"
        rubric = f"{r.evaluation.rubric_ratio * 100:.0f}%" if r.evaluation else "-"
        note = "; ".join(r.flags())[:80]
        lines.append(f"| {r.submission.student_name} | {r.submission.participant_id} "
                     f"| {r.score.final_grade:g} | {tests} | {rubric} | {note} |")
    lines.append("")

    unmatched = run.unmatched_worksheet_rows
    if unmatched:
        lines.append("## ワークシートにいるが提出がない学生")
        lines.append("")
        lines.extend(f"- {name}" for name in unmatched)
        lines.append("")

    return "\n".join(lines)
