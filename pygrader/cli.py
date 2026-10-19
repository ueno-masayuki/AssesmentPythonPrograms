"""コマンドラインインターフェース。

  python -m pygrader init  [--out assignment.yaml]
  python -m pygrader check --config assignment.yaml
  python -m pygrader grade --config assignment.yaml --submissions sub.zip \
                           [--worksheet ws.csv] [--out out/] [--no-llm] [--no-cache]
  python -m pygrader serve [--port 8000]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from .config import ConfigError, load_assignment

SAMPLE_PATH = Path(__file__).resolve().parent.parent / "sample_assignment.yaml"


def cmd_init(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if out.exists():
        print(f"エラー: {out} は既に存在します", file=sys.stderr)
        return 1
    shutil.copyfile(SAMPLE_PATH, out)
    print(f"課題設定のテンプレートを作成しました: {out}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from .pipeline import check_model_answer

    try:
        assignment = load_assignment(args.config)
    except (ConfigError, OSError) as e:
        print(f"設定エラー: {e}", file=sys.stderr)
        return 1
    print(f"課題設定 OK: {assignment.title}（テスト {len(assignment.tests)} 件 / "
          f"ルーブリック {len(assignment.rubric)} 基準）")
    if not assignment.model_answer.strip():
        print("回答例が未登録のため、テスト実行は省略します。")
        return 0
    outcome = check_model_answer(assignment)
    ok = True
    for r in outcome.results:
        mark = "OK " if r.passed else "NG "
        print(f"  {mark} {r.case.name}" + (f" — {r.detail}" if r.detail else ""))
        ok = ok and r.passed
    if not ok:
        print("回答例がテストに失敗しています。テストケースか回答例を見直してください。", file=sys.stderr)
        return 1
    print("回答例はすべてのテストに合格しました。")
    return 0


def cmd_grade(args: argparse.Namespace) -> int:
    from .pipeline import grade

    try:
        assignment = load_assignment(args.config)
    except (ConfigError, OSError) as e:
        print(f"設定エラー: {e}", file=sys.stderr)
        return 1

    def progress(done: int, total: int, name: str) -> None:
        print(f"  [{done}/{total}] {name}")

    try:
        run = grade(
            assignment,
            submissions_path=Path(args.submissions),
            worksheet_path=Path(args.worksheet) if args.worksheet else None,
            out_dir=Path(args.out),
            use_llm=not args.no_llm,
            use_cache=not args.no_cache,
            progress=progress,
        )
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    for w in run.warnings:
        print(f"警告: {w}")
    print(f"\n採点完了: {len(run.results)} 名（最大評点 {run.max_grade:g}）")
    for key, path in run.outputs.items():
        print(f"  {key}: {path}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    print(f"WebUIを起動します: http://127.0.0.1:{args.port}/")
    uvicorn.run("webapp.main:app", host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pygrader",
                                     description="Moodle課題のPythonプログラムを自動採点するツール")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="課題設定のテンプレートを作成")
    p.add_argument("--out", default="assignment.yaml")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("check", help="課題設定を検証し、回答例にテストを実行")
    p.add_argument("--config", required=True)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("grade", help="提出物を採点してMoodle用の出力を生成")
    p.add_argument("--config", required=True, help="課題設定YAML")
    p.add_argument("--submissions", required=True, help="Moodleの提出zipまたは展開済みフォルダ")
    p.add_argument("--worksheet", help="Moodleの採点ワークシートCSV")
    p.add_argument("--out", default="out", help="出力ディレクトリ（既定: out/）")
    p.add_argument("--no-llm", action="store_true", help="LLM評価を行わずテストのみで採点")
    p.add_argument("--no-cache", action="store_true", help="LLM応答キャッシュを使わない")
    p.set_defaults(func=cmd_grade)

    p = sub.add_parser("serve", help="WebUIを起動")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)
