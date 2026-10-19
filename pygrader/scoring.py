"""テスト点とルーブリック点を合成して最終評点を計算する。"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .config import Assignment


@dataclass
class ScoreBreakdown:
    test_ratio: float            # 0.0〜1.0
    rubric_ratio: float | None   # LLM評価なしのとき None
    weight_tests: float
    weight_rubric: float
    max_grade: float
    final_grade: float = field(init=False)

    def __post_init__(self) -> None:
        self.final_grade = _combine(
            self.test_ratio, self.rubric_ratio,
            self.weight_tests, self.weight_rubric, self.max_grade,
        )


def _combine(test_ratio: float, rubric_ratio: float | None,
             w_tests: float, w_rubric: float, max_grade: float) -> float:
    """ルーブリック点がない場合は重みをテスト側へ再正規化する。"""
    if rubric_ratio is None:
        w_rubric = 0.0
    total_w = w_tests + w_rubric
    if total_w <= 0:
        return 0.0
    ratio = (w_tests * test_ratio + w_rubric * (rubric_ratio or 0.0)) / total_w
    return round_half_up(ratio * max_grade, 1)


def round_half_up(value: float, digits: int = 1) -> float:
    q = Decimal(10) ** -digits
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def compute_score(assignment: Assignment, test_ratio: float,
                  rubric_ratio: float | None, max_grade: float) -> ScoreBreakdown:
    # テスト未定義の課題はルーブリックのみ、LLM評価なしはテストのみで採点
    # （_combine 側で残った重みに再正規化される）
    return ScoreBreakdown(
        test_ratio=test_ratio if assignment.tests else 0.0,
        rubric_ratio=rubric_ratio,
        weight_tests=assignment.weight_tests if assignment.tests else 0.0,
        weight_rubric=assignment.weight_rubric,
        max_grade=max_grade,
    )
