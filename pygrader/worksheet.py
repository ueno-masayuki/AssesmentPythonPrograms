"""Moodle採点ワークシートCSVの読み書き。

- 日本語・英語どちらのヘッダにも対応（NFKC正規化して照合）
- 全行・全列・列順を保持し、評点とフィードバックコメントだけを書き換える
- 読み込みは utf-8-sig（失敗時 cp932）、書き出しは utf-8-sig + QUOTE_ALL + CRLF
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# 正規化後ヘッダ → 論理名
_HEADER_MAP = {
    "identifier": "identifier",
    "識別子": "identifier",
    "full name": "fullname",
    "氏名": "fullname",
    "フルネーム": "fullname",
    "grade": "grade",
    "評点": "grade",
    "評定": "grade",
    "maximum grade": "maxgrade",
    "最大評点": "maxgrade",
    "最大評定": "maxgrade",
    "feedback comments": "feedback",
    "フィードバックコメント": "feedback",
}

_PARTICIPANT_RE = re.compile(r"(\d+)\s*$")


class WorksheetError(ValueError):
    pass


@dataclass
class Worksheet:
    header: list[str]
    rows: list[list[str]]
    columns: dict[str, int]          # 論理名 → 列index
    newline: str = "\r\n"
    source_path: Path | None = None
    max_grade: float | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        idx = self.columns.get("maxgrade")
        if idx is not None:
            for row in self.rows:
                try:
                    self.max_grade = float(row[idx].replace(",", ""))
                    break
                except (ValueError, IndexError):
                    continue

    # ---- 参照 -----------------------------------------------------------

    def participant_id(self, row: list[str]) -> str | None:
        idx = self.columns.get("identifier")
        if idx is None or idx >= len(row):
            return None
        m = _PARTICIPANT_RE.search(row[idx])
        return m.group(1) if m else None

    def fullname(self, row: list[str]) -> str:
        idx = self.columns.get("fullname")
        return row[idx] if idx is not None and idx < len(row) else ""

    def find_row(self, participant_id: str, fullname: str | None = None) -> list[str] | None:
        for row in self.rows:
            if self.participant_id(row) == participant_id:
                return row
        if fullname:
            norm = _norm(fullname)
            matches = [r for r in self.rows if _norm(self.fullname(r)) == norm]
            if len(matches) == 1:
                return matches[0]
        return None

    # ---- 書き込み -------------------------------------------------------

    def set_grade(self, row: list[str], grade: float, feedback: str) -> None:
        gi = self.columns.get("grade")
        fi = self.columns.get("feedback")
        if gi is None:
            raise WorksheetError("ワークシートに評点(Grade)列がありません")
        row[gi] = _format_grade(grade)
        if fi is not None:
            row[fi] = feedback

    def write(self, path: Path) -> None:
        buf = io.StringIO()
        writer = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator=self.newline)
        writer.writerow(self.header)
        writer.writerows(self.rows)
        path.write_text(buf.getvalue(), encoding="utf-8-sig", newline="")


def _format_grade(grade: float) -> str:
    # 80.0 → "80"、80.5 → "80.5"（Moodleはどちらも受け付ける）
    if grade == int(grade):
        return str(int(grade))
    return f"{grade:.1f}"


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).strip().lower()


def load_worksheet(path: Path | str) -> Worksheet:
    path = Path(path)
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp932")
        except UnicodeDecodeError as e:
            raise WorksheetError(f"ワークシートCSVの文字コードを判定できません: {e}") from e

    reader = csv.reader(io.StringIO(text))
    records = [row for row in reader if any(cell.strip() for cell in row)]
    if not records:
        raise WorksheetError("ワークシートCSVが空です")
    header, *rows = records

    columns: dict[str, int] = {}
    for i, cell in enumerate(header):
        logical = _HEADER_MAP.get(_norm(cell))
        if logical and logical not in columns:
            columns[logical] = i
    if "identifier" not in columns:
        raise WorksheetError(
            "ワークシートに識別子(Identifier)列がありません。Moodleの「採点ワークシート」"
            "CSVをダウンロードして指定してください。"
        )
    if "grade" not in columns:
        raise WorksheetError("ワークシートに評点(Grade)列がありません")

    # 行の列数をヘッダに合わせて揃える（短い行はパディング）
    width = len(header)
    rows = [row + [""] * (width - len(row)) if len(row) < width else row for row in rows]

    return Worksheet(header=header, rows=rows, columns=columns, source_path=path)
