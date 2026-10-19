import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def ensure_fixtures() -> Path:
    """フィクスチャが無ければ生成する。"""
    if not (FIXTURES / "submissions.zip").exists():
        sys.path.insert(0, str(ROOT / "scripts"))
        import make_fixtures

        FIXTURES.mkdir(parents=True, exist_ok=True)
        make_fixtures.make_submissions_zip(FIXTURES / "submissions.zip")
        make_fixtures.make_worksheet(FIXTURES / "worksheet_ja.csv", make_fixtures.WS_HEADERS_JA, "参加者")
        make_fixtures.make_worksheet(FIXTURES / "worksheet_en.csv", make_fixtures.WS_HEADERS_EN, "Participant ")
    return FIXTURES


@pytest.fixture()
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture()
def sample_assignment():
    from pygrader.config import Assignment, RubricCriterion, TestCase

    return Assignment(
        title="課題3: 成績の集計",
        description="標準入力から整数を読み込み、合計と平均を出力する。",
        expected_filename="kadai3.py",
        max_grade=100.0,
        tests=[
            TestCase(name="基本ケース", criterion="correctness", stdin="3\n10 20 30\n",
                     expected_stdout="合計: 60\n平均: 20.0\n", match="trim", weight=2),
            TestCase(name="関数テスト", criterion="correctness",
                     function="average", args=[[10, 20, 30]], expected=20.0),
        ],
        rubric=[
            RubricCriterion(id="correctness", name="動作の正しさ", points=80),
            RubricCriterion(id="readability", name="可読性", points=10),
            RubricCriterion(id="structure", name="構造", points=10),
        ],
        test_timeout=3.0,
    )
