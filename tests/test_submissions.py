from pathlib import Path

from pygrader.submissions import FOLDER_RE, decode_source, discover_submissions


def test_folder_regex_variants():
    m = FOLDER_RE.match("山田 太郎_100001_assignsubmission_file_")
    assert m and m.group("name") == "山田 太郎" and m.group("pid") == "100001"
    # 氏名にアンダースコアを含む場合
    m = FOLDER_RE.match("De_La_Cruz Juan_42_assignsubmission_file_")
    assert m and m.group("name") == "De_La_Cruz Juan" and m.group("pid") == "42"
    # 末尾アンダースコアなし・onlinetext形式
    m = FOLDER_RE.match("鈴木 花子_7_assignsubmission_onlinetext")
    assert m and m.group("pid") == "7"
    assert FOLDER_RE.match("README.txt") is None


def test_decode_source_encodings():
    text, enc, _ = decode_source("print('こんにちは')\n".encode("utf-8"))
    assert "こんにちは" in text
    text, enc, flags = decode_source("# 日本語コメント\nprint(1)\n".encode("cp932"))
    assert "日本語" in text and enc == "cp932" and flags


def test_discover_submissions_from_zip(fixtures: Path, tmp_path: Path):
    subs = discover_submissions(fixtures / "submissions.zip", tmp_path, expected_filename="kadai3.py")
    by_id = {s.participant_id: s for s in subs}
    assert len(subs) == 9

    assert by_id["100001"].has_code and by_id["100001"].code_path.name == "kadai3.py"
    # Shift_JIS提出: 読めてフラグが付く
    sjis = by_id["100005"]
    assert sjis.has_code and "合計" in sjis.code_text
    assert any("cp932" in f for f in sjis.flags)
    # 空提出
    assert not by_id["100006"].has_code
    # .txt提出はフォールバックで採点対象になる
    txt = by_id["100007"]
    assert txt.has_code and txt.code_path.name == "program.txt"
    assert any(".py" in f for f in txt.flags)
    # zip内zipの展開
    nested = by_id["100009"]
    assert nested.has_code and nested.code_path.name == "kadai3.py"


def test_discover_submissions_from_directory(fixtures: Path, tmp_path: Path):
    from pygrader.submissions import safe_extract_zip

    extracted = tmp_path / "ex"
    safe_extract_zip(fixtures / "submissions.zip", extracted)
    subs = discover_submissions(extracted, tmp_path / "work")
    assert len(subs) == 9
