"""学生コードに対するテスト実行。

非信頼コードのため、`python -I -B` のサブプロセスを新規一時ディレクトリ・
最小限の環境変数・タイムアウト付きで実行する（完全なサンドボックスではない）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .config import Assignment, TestCase

# 関数テストで学生のprint出力と結果を区別するための番兵マーカー
_SENTINEL = "__PYGRADER_RESULT__"

_HARNESS = """\
import builtins, json, sys

# トップレベルの input() でEOFにならないようスタブする
builtins.input = lambda *a, **k: "1"

src = open({module_path!r}, encoding="utf-8").read()
ns = {{"__name__": "student_module"}}  # __main__ ガード内の処理は実行しない
try:
    exec(compile(src, {module_path!r}, "exec"), ns)
except BaseException:
    pass  # トップレベルが失敗しても、定義済みの関数があれば評価する

fn = ns.get({function!r})
if not callable(fn):
    # トップレベル実行が途中で失敗した場合: 関数・クラス・import定義だけ抽出して再実行
    import ast
    try:
        tree = ast.parse(src)
        tree.body = [n for n in tree.body if isinstance(
            n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom))]
        ns = {{"__name__": "student_module"}}
        exec(compile(tree, "student_defs", "exec"), ns)
        fn = ns.get({function!r})
    except BaseException:
        pass
if not callable(fn):
    print({sentinel!r} + json.dumps({{"error": "function_not_found"}}))
    sys.exit(0)
args = json.loads({args_json!r})
try:
    result = fn(*args)
except Exception as e:
    print({sentinel!r} + json.dumps({{"error": "exception", "detail": f"{{type(e).__name__}}: {{e}}"}}))
    sys.exit(0)
try:
    payload = json.dumps({{"value": result}})
except TypeError:
    payload = json.dumps({{"repr": repr(result)}})
print({sentinel!r} + payload)
"""


@dataclass
class TestResult:
    case: TestCase
    status: str              # pass / wrong_output / error / timeout / not_run
    stdout: str = ""
    stderr: str = ""
    detail: str = ""         # 教員・学生向け説明（日本語）

    @property
    def passed(self) -> bool:
        return self.status == "pass"


@dataclass
class RunOutcome:
    results: list[TestResult] = field(default_factory=list)

    @property
    def score_ratio(self) -> float:
        total = sum(r.case.weight for r in self.results)
        if total <= 0:
            return 0.0
        return sum(r.case.weight for r in self.results if r.passed) / total

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)


def _minimal_env() -> dict[str, str]:
    env = {"PYTHONIOENCODING": "utf-8", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    if "PATH" in os.environ:
        env["PATH"] = os.environ["PATH"]
    if "SYSTEMROOT" in os.environ:  # Windows対応
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return env


def run_tests(code_text: str, assignment: Assignment, filename: str = "main.py") -> RunOutcome:
    """コード文字列に対して課題の全テストを実行する。"""
    outcome = RunOutcome()
    with tempfile.TemporaryDirectory(prefix="pygrader_") as tmp:
        tmpdir = Path(tmp)
        for case in assignment.tests:
            timeout = case.timeout if case.timeout is not None else assignment.test_timeout
            if case.is_function_test:
                outcome.results.append(_run_function_test(code_text, case, tmpdir, timeout, filename))
            else:
                outcome.results.append(_run_stdio_test(code_text, case, tmpdir, timeout, filename))
    return outcome


def _fresh_cwd(tmpdir: Path, code_text: str, filename: str) -> tuple[Path, Path]:
    """テストごとに新しい作業ディレクトリを作り、学生コードをコピーする。"""
    cwd = tmpdir / f"run_{uuid.uuid4().hex[:8]}"
    cwd.mkdir()
    script = cwd / (filename or "main.py")
    script.write_text(code_text, encoding="utf-8")
    return cwd, script


def _exec(cmd: list[str], *, stdin: str, cwd: Path, timeout: float) -> tuple[str, str, int] | None:
    """サブプロセス実行。タイムアウト時は None。"""
    try:
        proc = subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
            env=_minimal_env(),
        )
    except subprocess.TimeoutExpired:
        return None
    return proc.stdout, proc.stderr, proc.returncode


def _run_stdio_test(code_text: str, case: TestCase, tmpdir: Path, timeout: float, filename: str) -> TestResult:
    cwd, script = _fresh_cwd(tmpdir, code_text, filename)
    res = _exec(
        [sys.executable, "-I", "-B", script.name],
        stdin=case.stdin or "",
        cwd=cwd,
        timeout=timeout,
    )
    shutil.rmtree(cwd, ignore_errors=True)
    if res is None:
        return TestResult(case, "timeout", detail=f"{timeout}秒以内に終了しませんでした")
    stdout, stderr, returncode = res
    if returncode != 0:
        return TestResult(case, "error", stdout=stdout, stderr=stderr,
                          detail=_summarize_error(stderr))
    if _match_output(stdout, case):
        return TestResult(case, "pass", stdout=stdout, stderr=stderr)
    return TestResult(case, "wrong_output", stdout=stdout, stderr=stderr,
                      detail="出力が期待値と一致しませんでした")


def _run_function_test(code_text: str, case: TestCase, tmpdir: Path, timeout: float, filename: str) -> TestResult:
    cwd, script = _fresh_cwd(tmpdir, code_text, filename)
    harness_dir = tmpdir / f"harness_{uuid.uuid4().hex[:8]}"
    harness_dir.mkdir()
    harness = harness_dir / "harness.py"
    harness.write_text(
        _HARNESS.format(
            module_path=str(script.resolve()),
            function=case.function,
            args_json=json.dumps(case.args),
            sentinel=_SENTINEL,
        ),
        encoding="utf-8",
    )
    res = _exec(
        [sys.executable, "-I", "-B", str(harness.resolve())],
        stdin="",
        cwd=cwd,
        timeout=timeout,
    )
    shutil.rmtree(cwd, ignore_errors=True)
    shutil.rmtree(harness_dir, ignore_errors=True)
    if res is None:
        return TestResult(case, "timeout", detail=f"{timeout}秒以内に終了しませんでした")
    stdout, stderr, returncode = res

    payload = None
    for line in stdout.splitlines():
        if line.startswith(_SENTINEL):
            try:
                payload = json.loads(line[len(_SENTINEL):])
            except json.JSONDecodeError:
                payload = None
            break
    if payload is None:
        if returncode != 0:
            return TestResult(case, "error", stdout=stdout, stderr=stderr, detail=_summarize_error(stderr))
        return TestResult(case, "error", stdout=stdout, stderr=stderr,
                          detail="関数テストの結果を取得できませんでした")
    if payload.get("error") == "function_not_found":
        return TestResult(case, "error", detail=f"関数 {case.function} が定義されていません")
    if payload.get("error") == "exception":
        return TestResult(case, "error", detail=f"関数 {case.function} が例外を送出しました: {payload.get('detail', '')}")

    actual = payload.get("value", payload.get("repr"))
    if _values_equal(actual, case.expected):
        return TestResult(case, "pass")
    return TestResult(
        case, "wrong_output",
        detail=f"{case.function}({', '.join(map(repr, case.args))}) の返り値が期待値と一致しません"
               f"（期待: {case.expected!r} / 実際: {actual!r}）",
    )


def _values_equal(actual: object, expected: object) -> bool:
    if isinstance(expected, float) and isinstance(actual, (int, float)):
        return abs(float(actual) - expected) < 1e-6
    if isinstance(expected, list) and isinstance(actual, (list, tuple)):
        return list(actual) == expected
    return actual == expected


def _match_output(stdout: str, case: TestCase) -> bool:
    expected = case.expected_stdout or ""
    if case.match == "exact":
        return stdout == expected
    if case.match == "trim":
        return _trim(stdout) == _trim(expected)
    if case.match == "whitespace":
        return re.sub(r"\s+", " ", stdout).strip() == re.sub(r"\s+", " ", expected).strip()
    if case.match == "regex":
        return re.search(expected, stdout, re.MULTILINE) is not None
    raise ValueError(f"不明な照合モード: {case.match}")


def _trim(text: str) -> str:
    lines = [line.rstrip() for line in text.rstrip("\r\n").splitlines()]
    return "\n".join(lines)


def _summarize_error(stderr: str) -> str:
    lines = [l for l in stderr.strip().splitlines() if l.strip()]
    if not lines:
        return "実行時エラーが発生しました"
    return f"実行時エラー: {lines[-1][:200]}"
