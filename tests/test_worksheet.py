from pathlib import Path

import pytest

from pygrader.worksheet import WorksheetError, load_worksheet


@pytest.mark.parametrize("fname", ["worksheet_ja.csv", "worksheet_en.csv"])
def test_load_and_roundtrip(fixtures: Path, tmp_path: Path, fname: str):
    ws = load_worksheet(fixtures / fname)
    assert ws.max_grade == 100.0
    assert len(ws.rows) == 10

    row = ws.find_row("100001")
    assert row is not None
    ws.set_grade(row, 85.0, "よくできました")

    out = tmp_path / "filled.csv"
    ws.write(out)

    # BOM付きで出力される
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in raw

    # 再読込して値と他の列が保持されていることを確認
    ws2 = load_worksheet(out)
    assert ws2.header == ws.header
    row2 = ws2.find_row("100001")
    assert row2[ws2.columns["grade"]] == "85"
    assert row2[ws2.columns["feedback"]] == "よくできました"
    # 触っていない行は空のまま
    row3 = ws2.find_row("100010")
    assert row3[ws2.columns["grade"]] == ""


def test_find_by_fullname_fallback(fixtures: Path):
    ws = load_worksheet(fixtures / "worksheet_ja.csv")
    row = ws.find_row("999999", fullname="山田 太郎")
    assert row is not None and ws.fullname(row) == "山田 太郎"


def test_missing_identifier_column(tmp_path: Path):
    bad = tmp_path / "bad.csv"
    bad.write_text("名前,点数\nA,1\n", encoding="utf-8-sig")
    with pytest.raises(WorksheetError):
        load_worksheet(bad)


def test_cp932_worksheet(fixtures: Path, tmp_path: Path):
    # Excelでcp932保存し直されたケース
    text = (fixtures / "worksheet_ja.csv").read_text(encoding="utf-8-sig")
    p = tmp_path / "sjis.csv"
    p.write_bytes(text.encode("cp932"))
    ws = load_worksheet(p)
    assert ws.find_row("100001") is not None
