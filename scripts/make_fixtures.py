"""テスト・動作確認用の合成提出物zipとワークシートCSVを生成する。

使い方: python scripts/make_fixtures.py [出力先ディレクトリ=tests/fixtures]
"""

from __future__ import annotations

import csv
import io
import sys
import zipfile
from pathlib import Path

STUDENTS = [
    # (氏名, 参加者ID, ファイル名, コード or None, エンコーディング)
    ("山田 太郎", "100001", "kadai3.py", """\
# 合計と平均を計算するプログラム
n = int(input())
nums = list(map(int, input().split()))
total = sum(nums)
print(f"合計: {total}")
print(f"平均: {total / n}")

def average(xs):
    return sum(xs) / len(xs)
""", "utf-8"),
    ("鈴木 花子", "100002", "kadai3.py", """\
n = int(input())
nums = list(map(int, input().split()))
print("合計:", sum(nums))        # 出力形式が違う
print("平均:", sum(nums) // n)   # 整数除算のバグ

def average(xs):
    return sum(xs) // len(xs)
""", "utf-8"),
    ("佐藤 次郎", "100003", "kadai3.py", """\
n = int(input())
nums = list(map(int, input().split()))
print(f"合計: {sum(nums)}")
print(f"平均: {undefined_variable}")  # NameError
""", "utf-8"),
    ("田中 三郎", "100004", "kadai3.py", """\
while True:
    pass  # 無限ループ
""", "utf-8"),
    ("高橋 四子", "100005", "kadai3.py", """\
# Shift_JISで保存されたファイル（コメントに日本語）
n = int(input())
nums = list(map(int, input().split()))
total = sum(nums)
print(f"合計: {total}")
print(f"平均: {total / n}")

def average(xs):
    return sum(xs) / len(xs)
""", "cp932"),
    ("伊藤 五郎", "100006", None, None, None),  # 空の提出
    ("渡辺 六実", "100007", "program.txt", """\
n = int(input())
nums = list(map(int, input().split()))
total = sum(nums)
print(f"合計: {total}")
print(f"平均: {total / n}")

def average(xs):
    return sum(xs) / len(xs)
""", "utf-8"),  # .txtで提出
    ("中村 七海", "100008", "kadai3.py", """\
# 山田さんのコードとほぼ同一（類似検出テスト用）
n = int(input())
nums = list(map(int, input().split()))
total = sum(nums)
print(f"合計: {total}")
print(f"平均: {total / n}")

def average(xs):
    return sum(xs) / len(xs)
""", "utf-8"),
]

WS_HEADERS_JA = ["識別子", "氏名", "メールアドレス", "ステータス", "評点", "最大評点",
                 "評点を変更できます", "最終更新日時 (提出)", "最終更新日時 (評点)", "フィードバックコメント"]
WS_HEADERS_EN = ["Identifier", "Full name", "Email address", "Status", "Grade", "Maximum grade",
                 "Grade can be changed", "Last modified (submission)", "Last modified (grade)", "Feedback comments"]


def make_submissions_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, pid, filename, code, enc in STUDENTS:
            folder = f"{name}_{pid}_assignsubmission_file_"
            if filename is None:
                zf.writestr(zipfile.ZipInfo(folder + "/"), b"")
                continue
            zf.writestr(f"{folder}/{filename}", code.encode(enc))
        # zip内zipの提出者
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as izf:
            izf.writestr("kadai3.py", STUDENTS[0][3].encode("utf-8"))
        zf.writestr("小林 八雲_100009_assignsubmission_file_/teisyutu.zip", inner.getvalue())


def make_worksheet(path: Path, headers: list[str], participant_prefix: str) -> None:
    rows = []
    all_students = [(n, p) for n, p, *_ in STUDENTS] + [("小林 八雲", "100009"), ("欠席 九郎", "100010")]
    for name, pid in all_students:
        rows.append([
            f"{participant_prefix}{pid}", name, f"user{pid}@example.ac.jp",
            "評定のために提出されました" if participant_prefix == "参加者" else "Submitted for grading",
            "", "100", "Yes", "-", "-", "",
        ])
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    w.writerow(headers)
    w.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8-sig", newline="")


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "tests" / "fixtures"
    out.mkdir(parents=True, exist_ok=True)
    make_submissions_zip(out / "submissions.zip")
    make_worksheet(out / "worksheet_ja.csv", WS_HEADERS_JA, "参加者")
    make_worksheet(out / "worksheet_en.csv", WS_HEADERS_EN, "Participant ")
    print(f"フィクスチャを生成しました: {out}")


if __name__ == "__main__":
    main()
