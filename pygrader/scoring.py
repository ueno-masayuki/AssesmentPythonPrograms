"""ルーブリックにもとづく評点計算。

最終評点 = Σ(各基準の得点)。
- テストが紐づく基準: 得点 = 配点 × (合格テストの重み合計 / 紐づくテストの重み合計)
- テストが紐づかない基準: LLMの基準別スコア（0〜配点にクランプ済み）
- LLM評価が使えない場合: LLM基準を除外し、テスト基準の得点率で再正規化
- ワークシートの最大評点がルーブリック合計と異なる場合は比例スケール
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from .config import Assignment, RubricCriterion

if TYPE_CHECKING:
    from .llm import LLMEvaluation
    from .runner import RunOutcome


@dataclass
class CriterionResult:
    criterion: RubricCriterion
    earned: float
    source: str      # "tests" / "llm" / "none"（LLM縮退時）
    note: str = ""   # 内訳説明（日本語）


@dataclass
class ScoreBreakdown:
    criteria: list[CriterionResult] = field(default_factory=list)
    max_grade: float = 0.0
    renormalized: bool = False  # LLM評価なしでテスト基準から再正規化した
    final_grade: float = 0.0

    def breakdown_text(self) -> str:
        """「動作 56/70, 可読性 8/10」形式の内訳（CSVコメント・レポート用）。"""
        parts = [
            f"{c.criterion.name} {round_half_up(c.earned):g}/{c.criterion.points:g}"
            for c in self.criteria if c.source != "none"
        ]
        return ", ".join(parts)


def round_half_up(value: float, digits: int = 1) -> float:
    q = Decimal(10) ** -digits
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def compute_score(
    assignment: Assignment,
    outcome: "RunOutcome | None",
    evaluation: "LLMEvaluation | None",
    max_grade: float,
) -> ScoreBreakdown:
    bd = ScoreBreakdown(max_grade=max_grade)

    # ルーブリックなし（テストのみの課題）: テスト得点率 × 最大評点
    if not assignment.rubric:
        ratio = outcome.score_ratio if outcome else 0.0
        bd.final_grade = round_half_up(ratio * max_grade)
        return bd

    llm_scores = {c.criterion_id: c for c in evaluation.criteria} if evaluation else {}

    for r in assignment.rubric:
        linked = assignment.tests_for(r.id)
        if linked:
            total_w = sum(t.weight for t in linked)
            passed_w = 0.0
            passed_n = 0
            if outcome:
                # run_tests は assignment.tests と同一の TestCase オブジェクトを使う
                by_case = {id(res.case): res for res in outcome.results}
                for t in linked:
                    res = by_case.get(id(t))
                    if res is not None and res.passed:
                        passed_w += t.weight
                        passed_n += 1
            ratio = passed_w / total_w if total_w > 0 else 0.0
            bd.criteria.append(CriterionResult(
                criterion=r, earned=r.points * ratio, source="tests",
                note=f"紐づくテスト {passed_n}/{len(linked)} 件合格",
            ))
        elif evaluation is not None:
            c = llm_scores.get(r.id)
            earned = max(0.0, min(c.score, r.points)) if c else 0.0
            bd.criteria.append(CriterionResult(
                criterion=r, earned=earned, source="llm",
                note=(c.reason_ja if c else "AI評価の結果が得られませんでした"),
            ))
        else:
            bd.criteria.append(CriterionResult(
                criterion=r, earned=0.0, source="none",
                note="LLM評価なしのため未評価（テスト基準から換算）",
            ))

    scored = [c for c in bd.criteria if c.source != "none"]
    scored_points = sum(c.criterion.points for c in scored)
    earned = sum(c.earned for c in scored)

    if any(c.source == "none" for c in bd.criteria):
        # LLM評価が使えない: 評価できた基準の得点率で全体を再正規化
        bd.renormalized = True
        ratio = earned / scored_points if scored_points > 0 else 0.0
        bd.final_grade = round_half_up(ratio * max_grade)
        return bd

    total_points = sum(c.criterion.points for c in bd.criteria)
    if total_points > 0 and abs(total_points - max_grade) >= 0.01:
        # ワークシートの最大評点がルーブリック合計と異なる場合は比例スケール
        bd.final_grade = round_half_up(earned / total_points * max_grade)
    else:
        bd.final_grade = round_half_up(earned)
    return bd
