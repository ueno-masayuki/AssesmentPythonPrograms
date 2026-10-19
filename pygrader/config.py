"""課題定義(YAML)の読み込みと検証。

1課題 = 1 YAMLファイル。WebUI・CLIの双方がこのモジュールを通して読み書きする。
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_TIMEOUT = 5.0
MATCH_MODES = ("exact", "trim", "whitespace", "regex")


class ConfigError(ValueError):
    """課題定義の形式エラー。メッセージは教員向けに日本語で持つ。"""


@dataclass
class TestCase:
    __test__ = False  # pytestの収集対象ではない

    name: str
    criterion: str | None = None  # 紐づけるルーブリック基準のid
    weight: float = 1.0
    timeout: float | None = None  # Noneなら tests.timeout を使う
    # stdin/stdout テスト
    stdin: str | None = None
    expected_stdout: str | None = None
    match: str = "trim"
    # 関数テスト
    function: str | None = None
    args: list[Any] = field(default_factory=list)
    expected: Any = None

    @property
    def is_function_test(self) -> bool:
        return self.function is not None

    def validate(self, index: int) -> None:
        label = f"tests.cases[{index}] ({self.name})"
        if self.match not in MATCH_MODES:
            raise ConfigError(f"{label}: match は {MATCH_MODES} のいずれかにしてください: {self.match!r}")
        if self.weight <= 0:
            raise ConfigError(f"{label}: weight は正の数にしてください")
        if self.is_function_test:
            if self.expected is None:
                raise ConfigError(f"{label}: 関数テストには expected が必要です")
        else:
            if self.expected_stdout is None:
                raise ConfigError(f"{label}: expected_stdout か function のどちらかが必要です")
        if self.match == "regex" and self.expected_stdout is not None:
            try:
                re.compile(self.expected_stdout)
            except re.error as e:
                raise ConfigError(f"{label}: expected_stdout が正規表現として不正です: {e}") from e


@dataclass
class RubricCriterion:
    id: str
    name: str
    points: float
    description: str = ""

    def validate(self, index: int) -> None:
        if not self.id or not re.fullmatch(r"[A-Za-z0-9_\-]+", self.id):
            raise ConfigError(f"rubric[{index}]: id は英数字・ハイフン・アンダースコアで指定してください: {self.id!r}")
        if self.points <= 0:
            raise ConfigError(f"rubric[{index}] ({self.id}): points は正の数にしてください")


@dataclass
class Assignment:
    title: str
    description: str = ""
    expected_filename: str | None = None
    max_grade: float | None = 100.0
    test_timeout: float = DEFAULT_TIMEOUT
    tests: list[TestCase] = field(default_factory=list)
    rubric: list[RubricCriterion] = field(default_factory=list)
    model_answer: str = ""
    llm_model: str = DEFAULT_MODEL
    llm_enabled: bool = True
    similarity_check: bool = True
    feedback_filename: str = "feedback.md"

    def validate(self) -> None:
        if not self.title.strip():
            raise ConfigError("title は必須です")
        # tests/rubric が両方空でも下書きとして有効。採点開始時に pipeline.grade() が検査する。
        if self.max_grade is not None and self.max_grade <= 0:
            raise ConfigError("max_grade は正の数にしてください")
        if self.test_timeout <= 0:
            raise ConfigError("tests.timeout は正の数にしてください")
        for i, t in enumerate(self.tests):
            t.validate(i)
        for i, r in enumerate(self.rubric):
            r.validate(i)
        ids = [r.id for r in self.rubric]
        if len(ids) != len(set(ids)):
            raise ConfigError("rubric の id が重複しています")
        if self.rubric:
            # テストの紐づけ先が存在すること
            for t in self.tests:
                if t.criterion and t.criterion not in ids:
                    raise ConfigError(
                        f"テスト「{t.name}」の評価基準 {t.criterion!r} がルーブリックにありません")
            # 配点合計 = 最大評点 を強制
            if self.max_grade is not None and abs(self.rubric_total_points - self.max_grade) >= 0.01:
                raise ConfigError(
                    f"ルーブリックの配点合計（{self.rubric_total_points:g}点）が"
                    f"最大評点（{self.max_grade:g}点）と一致していません。"
                    "配点を調整してください（WebUIの「配点を最大評点に合わせる」ボタンが使えます）。"
                )

    @property
    def rubric_total_points(self) -> float:
        return sum(r.points for r in self.rubric)

    def tests_for(self, criterion_id: str) -> list[TestCase]:
        return [t for t in self.tests if t.criterion == criterion_id]

    @property
    def test_criteria(self) -> list[RubricCriterion]:
        """テストが1件以上紐づく基準（テスト結果から得点を計算する）。"""
        linked = {t.criterion for t in self.tests if t.criterion}
        return [r for r in self.rubric if r.id in linked]

    @property
    def llm_criteria(self) -> list[RubricCriterion]:
        """テストが紐づかない基準（LLMが評価する）。"""
        linked = {t.criterion for t in self.tests if t.criterion}
        return [r for r in self.rubric if r.id not in linked]

    # ---- YAML入出力 ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "title": self.title,
            "description": self.description,
            "max_grade": self.max_grade,
            "tests": {
                "timeout": self.test_timeout,
                "cases": [_testcase_to_dict(t) for t in self.tests],
            },
            "rubric": [
                {"id": r.id, "name": r.name, "points": r.points, **({"description": r.description} if r.description else {})}
                for r in self.rubric
            ],
            "model_answer": self.model_answer,
            "llm": {"model": self.llm_model, "enabled": self.llm_enabled},
            "similarity_check": self.similarity_check,
            "feedback_file": self.feedback_filename,
        }
        if self.expected_filename:
            d["expected_filename"] = self.expected_filename
        return d

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False, default_flow_style=False)
        path.write_text(text, encoding="utf-8")


def _testcase_to_dict(t: TestCase) -> dict[str, Any]:
    d: dict[str, Any] = {"name": t.name, "weight": t.weight}
    if t.criterion:
        d["criterion"] = t.criterion
    if t.timeout is not None:
        d["timeout"] = t.timeout
    if t.is_function_test:
        d.update({"function": t.function, "args": t.args, "expected": t.expected})
    else:
        d.update({"stdin": t.stdin or "", "expected_stdout": t.expected_stdout, "match": t.match})
    return d


def _parse_testcase(raw: dict[str, Any], index: int) -> TestCase:
    if not isinstance(raw, dict):
        raise ConfigError(f"tests.cases[{index}] はマッピングで指定してください")
    known = {"name", "criterion", "weight", "timeout", "stdin", "expected_stdout", "match",
             "function", "args", "expected"}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"tests.cases[{index}]: 不明なキーがあります: {sorted(unknown)}")
    return TestCase(
        name=str(raw.get("name") or f"テスト{index + 1}"),
        criterion=str(raw["criterion"]) if raw.get("criterion") else None,
        weight=float(raw.get("weight", 1.0)),
        timeout=float(raw["timeout"]) if raw.get("timeout") is not None else None,
        stdin=str(raw["stdin"]) if raw.get("stdin") is not None else None,
        expected_stdout=str(raw["expected_stdout"]) if raw.get("expected_stdout") is not None else None,
        match=str(raw.get("match", "trim")),
        function=str(raw["function"]) if raw.get("function") else None,
        args=list(raw.get("args", [])),
        expected=raw.get("expected"),
    )


def assignment_from_dict(data: dict[str, Any]) -> Assignment:
    if not isinstance(data, dict):
        raise ConfigError("課題定義のルートはマッピングにしてください")
    # 旧形式の weights キーは無視する（後方互換）
    tests_block = data.get("tests") or {}
    if isinstance(tests_block, list):  # cases直書きも許容
        tests_block = {"cases": tests_block}
    llm_block = data.get("llm") or {}

    rubric: list[RubricCriterion] = []
    for i, raw in enumerate(data.get("rubric") or []):
        if not isinstance(raw, dict):
            raise ConfigError(f"rubric[{i}] はマッピングで指定してください")
        rubric.append(
            RubricCriterion(
                id=str(raw.get("id") or f"criterion{i + 1}"),
                name=str(raw.get("name") or raw.get("id") or f"基準{i + 1}"),
                points=float(raw.get("points", 0)),
                description=str(raw.get("description", "")),
            )
        )

    a = Assignment(
        title=str(data.get("title", "")),
        description=str(data.get("description", "")),
        expected_filename=(str(data["expected_filename"]) if data.get("expected_filename") else None),
        max_grade=(float(data["max_grade"]) if data.get("max_grade") is not None else None),
        test_timeout=float(tests_block.get("timeout", DEFAULT_TIMEOUT)),
        tests=[_parse_testcase(raw, i) for i, raw in enumerate(tests_block.get("cases") or [])],
        rubric=rubric,
        model_answer=str(data.get("model_answer") or ""),
        llm_model=str(llm_block.get("model", DEFAULT_MODEL)),
        llm_enabled=bool(llm_block.get("enabled", True)),
        similarity_check=bool(data.get("similarity_check", True)),
        feedback_filename=str(data.get("feedback_file", "feedback.md")),
    )
    a.validate()
    return a


def load_assignment(path: Path | str) -> Assignment:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"YAMLの解析に失敗しました: {e}") from e
    if data is None:
        raise ConfigError("課題定義が空です")
    return assignment_from_dict(data)


def replace(a: Assignment, **changes: Any) -> Assignment:
    return dataclasses.replace(a, **changes)
