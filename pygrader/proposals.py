"""提案機能: 課題説明から回答例・ルーブリック・テストケースをClaudeに生成させる。

生成結果は下書きであり、教員がWebUI上で確認・修正してから保存する。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .config import Assignment, MATCH_MODES
from .llm import LLMUnavailable, _client

_SYSTEM = """\
あなたは大学のプログラミング演習（Python）の教材作成を手伝うアシスタントです。
与えられた課題に対して、教員が利用する教材（回答例・採点基準・テストケース）の
下書きを作成してください。対象は初学者向けの授業です。
"""


class ModelAnswerProposal(BaseModel):
    code: str = Field(description="回答例（模範解答）のPythonコード全体")
    explanation_ja: str = Field(description="コードの要点の説明（日本語・2〜4文）")


class RubricCriterionProposal(BaseModel):
    id: str = Field(description="基準のid（英小文字とアンダースコア）")
    name_ja: str = Field(description="基準名（日本語・簡潔に）")
    points: float = Field(description="配点")
    description_ja: str = Field(description="評価の観点の説明（日本語・1文）")


class RubricProposal(BaseModel):
    criteria: list[RubricCriterionProposal] = Field(description="3〜5個程度の採点基準")


def normalize_points(points: list[float], total: float) -> list[float]:
    """配点リストを比例スケールして、合計がちょうど total になる整数配点にする。

    丸めで生じた端数は配点が最大の基準で調整する。どうしても整数で合わせられない
    端数（totalが非整数等）は最後の要素に寄せる。
    """
    if not points or total <= 0:
        return list(points)
    cur = sum(points)
    if cur <= 0:
        base = total / len(points)
        scaled = [base] * len(points)
    else:
        scaled = [p * total / cur for p in points]
    rounded = [max(1.0, float(round(p))) for p in scaled]
    diff = total - sum(rounded)
    if abs(diff) >= 0.5:
        # 整数単位のずれは最大配点の基準に足し引きする（1点未満にはしない）
        order = sorted(range(len(rounded)), key=lambda i: -rounded[i])
        step = 1.0 if diff > 0 else -1.0
        remaining = round(abs(diff))
        for _ in range(int(remaining)):
            for i in order:
                if step > 0 or rounded[i] > 1.0:
                    rounded[i] += step
                    break
    # 小数の端数（totalが非整数の場合）は先頭に寄せる
    frac = total - sum(rounded)
    if abs(frac) >= 0.01:
        rounded[0] = max(0.5, rounded[0] + frac)
    return rounded


class TestCaseProposal(BaseModel):
    name_ja: str = Field(description="テストケース名（日本語）")
    stdin: str = Field(description="標準入力に与える文字列（改行含む）")
    expected_stdout: str = Field(description="期待される標準出力")
    match: str = Field(description=f"照合モード: {', '.join(MATCH_MODES)} のいずれか（通常は trim）")
    weight: float = Field(description="重み（通常は1）")
    criterion: str = Field(description="紐づけるルーブリック基準のid（指定された一覧から選ぶ）")


class TestsProposal(BaseModel):
    cases: list[TestCaseProposal] = Field(description="3〜6個程度のテストケース")


def _assignment_context(assignment: Assignment) -> str:
    parts = [f"# 課題\n## {assignment.title}\n{assignment.description.strip() or '(課題説明は未記入)'}"]
    if assignment.expected_filename:
        parts.append(f"提出ファイル名: {assignment.expected_filename}")
    if assignment.tests:
        lines = []
        for t in assignment.tests:
            if t.is_function_test:
                lines.append(f"- {t.name}: 関数 {t.function}({t.args!r}) → 期待値 {t.expected!r}")
            else:
                lines.append(f"- {t.name}: 入力 {t.stdin!r} → 期待出力 {t.expected_stdout!r}")
        parts.append("# 登録済みテストケース\n" + "\n".join(lines))
    if assignment.rubric:
        lines = [f"- {r.id}: {r.name}（{r.points:g}点）" for r in assignment.rubric]
        parts.append("# 登録済みルーブリック\n" + "\n".join(lines))
    if assignment.model_answer.strip():
        parts.append(f"# 登録済み回答例\n```python\n{assignment.model_answer.strip()}\n```")
    return "\n\n".join(parts)


def _ask(assignment: Assignment, instruction: str, output_model: type[BaseModel]):
    client = _client()
    import anthropic

    try:
        response = client.messages.parse(
            model=assignment.llm_model,
            max_tokens=4000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": _assignment_context(assignment) + "\n\n" + instruction}],
            output_format=output_model,
        )
    except anthropic.RateLimitError as e:
        raise LLMUnavailable(f"レート制限のため提案を生成できませんでした: {e}") from e
    except anthropic.APIStatusError as e:
        raise LLMUnavailable(f"APIエラーのため提案を生成できませんでした (status={e.status_code})") from e
    except anthropic.APIConnectionError as e:
        raise LLMUnavailable(f"API接続エラーのため提案を生成できませんでした: {e}") from e
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise LLMUnavailable("提案の生成に失敗しました")
    return response.parsed_output


def propose_model_answer(assignment: Assignment) -> ModelAnswerProposal:
    if not assignment.description.strip():
        raise LLMUnavailable("課題説明を先に記入してください")
    return _ask(
        assignment,
        "この課題の回答例（模範解答）を作成してください。"
        "授業レベルに合った平易なPythonで、適度にコメントを付けてください。"
        "登録済みテストケースがあれば、それをすべて満たすコードにしてください。",
        ModelAnswerProposal,
    )


def propose_rubric(assignment: Assignment) -> RubricProposal:
    if not assignment.description.strip():
        raise LLMUnavailable("課題説明を先に記入してください")
    total = assignment.max_grade or 100
    proposal = _ask(
        assignment,
        f"この課題の採点に使うルーブリック（採点基準）を提案してください。"
        f"基準は3〜5個、配点の合計はちょうど {total:g} 点にしてください。"
        "必ず、自動テストで採点する「動作の正しさ」に相当する基準（id: correctness）を"
        "1つ含め、そこに配点の過半を割り当ててください。"
        "残りは初学者の提出物で差がつきやすい観点（可読性・構造・入出力の扱いなど）に"
        "配分してください。",
        RubricProposal,
    )
    # LLMの出力に依存せず、合計がちょうど最大評点になるよう正規化する
    normalized = normalize_points([c.points for c in proposal.criteria], float(total))
    for c, p in zip(proposal.criteria, normalized):
        c.points = p
    return proposal


def propose_tests(assignment: Assignment) -> TestsProposal:
    if not assignment.description.strip():
        raise LLMUnavailable("課題説明を先に記入してください")
    rubric_ids = [r.id for r in assignment.rubric]
    criterion_note = (
        f"各テストの criterion は {rubric_ids} から選んでください"
        "（通常は『動作の正しさ』に相当する基準）。"
        if rubric_ids else "criterion は 'correctness' としてください。"
    )
    proposal = _ask(
        assignment,
        "この課題の自動採点に使う標準入出力テストケースを3〜6個提案してください。"
        "基本ケースに加えて、境界値や少し意地悪なケースも含めてください。"
        "expected_stdout は課題説明の出力形式に正確に従ってください。" + criterion_note,
        TestsProposal,
    )
    # 既定の紐づけ先: テストが既に紐づいている基準 → 先頭の基準
    linked = {t.criterion for t in assignment.tests if t.criterion}
    default_id = next((r.id for r in assignment.rubric if r.id in linked),
                      rubric_ids[0] if rubric_ids else "")
    for c in proposal.cases:
        if c.match not in MATCH_MODES:
            c.match = "trim"
        if c.weight <= 0:
            c.weight = 1.0
        if rubric_ids and c.criterion not in rubric_ids:
            c.criterion = default_id
    return proposal
