from pygrader.config import Assignment, TestCase
from pygrader.runner import run_tests

CORRECT = """\
n = int(input())
nums = list(map(int, input().split()))
total = sum(nums)
print(f"合計: {total}")
print(f"平均: {total / n}")

def average(xs):
    return sum(xs) / len(xs)
"""


def _assignment(**kw):
    defaults = dict(
        title="t",
        tests=[
            TestCase(name="基本", stdin="3\n10 20 30\n", expected_stdout="合計: 60\n平均: 20.0\n", weight=2),
            TestCase(name="関数", function="average", args=[[10, 20, 30]], expected=20.0),
        ],
        test_timeout=3.0,
    )
    defaults.update(kw)
    return Assignment(**defaults)


def test_all_pass():
    outcome = run_tests(CORRECT, _assignment())
    assert [r.status for r in outcome.results] == ["pass", "pass"]
    assert outcome.score_ratio == 1.0


def test_wrong_output_and_weights():
    code = CORRECT.replace("合計", "ごうけい")
    outcome = run_tests(code, _assignment())
    assert outcome.results[0].status == "wrong_output"
    assert outcome.results[1].status == "pass"  # 関数は正しい
    assert outcome.score_ratio == 1 / 3  # weight 2が落ち、1が通る


def test_runtime_error():
    outcome = run_tests("print(undefined)\n", _assignment())
    assert outcome.results[0].status == "error"
    assert "エラー" in outcome.results[0].detail


def test_timeout():
    outcome = run_tests("while True: pass\n", _assignment(test_timeout=1.0))
    assert all(r.status == "timeout" for r in outcome.results)


def test_function_not_found():
    outcome = run_tests("print('合計: 60')\nprint('平均: 20.0')\n", _assignment())
    assert outcome.results[1].status == "error"
    assert "average" in outcome.results[1].detail


def test_student_prints_dont_break_function_test():
    code = CORRECT + "\nprint('余計な出力')\n"
    outcome = run_tests(code, _assignment())
    assert outcome.results[1].status == "pass"


def test_match_modes():
    a = _assignment(tests=[
        TestCase(name="trim", stdin="", expected_stdout="hello\n", match="trim"),
        TestCase(name="exact", stdin="", expected_stdout="hello\n", match="exact"),
        TestCase(name="ws", stdin="", expected_stdout="a b", match="whitespace"),
        TestCase(name="re", stdin="", expected_stdout=r"合計:\s*60", match="regex"),
    ])
    code = "print('hello')\nprint('a    b')\nprint('合計: 60')\n"
    outcome = run_tests(code, a)
    statuses = {r.case.name: r.status for r in outcome.results}
    assert statuses["trim"] == "wrong_output"  # 余計な行があるのでtrimでも不一致
    a2 = _assignment(tests=[TestCase(name="trim", stdin="", expected_stdout="hello  \n", match="trim")])
    assert run_tests("print('hello')\n", a2).results[0].status == "pass"
    assert statuses["re"] == "pass"
    assert statuses["ws"] == "wrong_output"
