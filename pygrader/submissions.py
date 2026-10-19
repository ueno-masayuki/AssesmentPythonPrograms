"""Moodle「すべての提出をダウンロード」zip / 展開済みフォルダの解析。

- フォルダ名 `<氏名>_<参加者ID>_assignsubmission_file_` から学生を特定する
- 学生ごとに採点対象の .py ファイルを選択する（zip内zipは1段展開）
- 文字コードを判定してソースをテキスト化する
"""

from __future__ import annotations

import ast
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# Moodleの提出フォルダ名。氏名にアンダースコアや空白が含まれても
# 最後の `_<数字>_assignsubmission_<type>_?` を区切りとして解釈する。
FOLDER_RE = re.compile(r"^(?P<name>.+)_(?P<pid>\d+)_assignsubmission_(?P<subtype>\w+?)_?$")

# フィードバックzip生成時にも同じ形式のフォルダ名を使う（Moodle側の照合はID部分）
FEEDBACK_FOLDER_SUFFIX = "assignsubmission_file_"

ENCODING_CANDIDATES = ("utf-8-sig", "cp932", "euc_jp")


@dataclass
class Submission:
    student_name: str
    participant_id: str
    folder_name: str          # zip内のトップレベルフォルダ名（フィードバックzipで再利用）
    folder_path: Path
    code_path: Path | None = None   # 採点対象ファイル（なければ無効提出）
    code_text: str = ""
    encoding: str = ""
    flags: list[str] = field(default_factory=list)  # 教員向けの注意点（日本語）

    @property
    def has_code(self) -> bool:
        return self.code_path is not None


class SubmissionError(ValueError):
    pass


# ---------------------------------------------------------------------------
# zip展開（パストラバーサル対策）
# ---------------------------------------------------------------------------

def safe_extract_zip(zip_path: Path, dest: Path) -> None:
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            # Moodleのzipはファイル名がUTF-8だが、フラグ無しだとcp437扱いになるので補正
            name = _fix_zip_name(info)
            target = (dest / name).resolve()
            if not target.is_relative_to(dest):
                raise SubmissionError(f"zip内に不正なパスがあります: {info.filename!r}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src:
                target.write_bytes(src.read())


def _fix_zip_name(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if info.flag_bits & 0x800:  # UTF-8フラグあり
        return name
    try:
        return name.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        try:
            return name.encode("cp437").decode("cp932")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return name


# ---------------------------------------------------------------------------
# 文字コード判定
# ---------------------------------------------------------------------------

def decode_source(data: bytes) -> tuple[str, str, list[str]]:
    """バイト列を (text, encoding, flags) に変換する。"""
    candidates: list[tuple[str, str]] = []
    for enc in ENCODING_CANDIDATES:
        try:
            candidates.append((data.decode(enc), enc))
        except UnicodeDecodeError:
            continue
    if not candidates:
        text = data.decode("utf-8", errors="replace")
        return text, "utf-8(置換あり)", ["文字コードを判定できず、一部の文字を置換して読み込みました"]
    # 複数候補があれば、Pythonとして構文解析できるものを優先する
    for text, enc in candidates:
        if _parses(text):
            flags = [] if enc in ("utf-8-sig",) else [f"ファイルの文字コードが {enc} でした（UTF-8を推奨）"]
            return text, enc, flags
    text, enc = candidates[0]
    flags = [] if enc == "utf-8-sig" else [f"ファイルの文字コードが {enc} でした（UTF-8を推奨）"]
    return text, enc, flags


def _parses(text: str) -> bool:
    try:
        ast.parse(text)
        return True
    except (SyntaxError, ValueError):
        return False


# ---------------------------------------------------------------------------
# 提出物の走査
# ---------------------------------------------------------------------------

def discover_submissions(source: Path, workdir: Path, expected_filename: str | None = None) -> list[Submission]:
    """zipまたは展開済みフォルダから Submission 一覧を作る。

    workdir: zip展開先（source がディレクトリの場合は使わない）。
    """
    source = Path(source)
    if source.is_file() and source.suffix.lower() == ".zip":
        root = workdir / "extracted"
        safe_extract_zip(source, root)
    elif source.is_dir():
        root = source
    else:
        raise SubmissionError(f"提出物は zip ファイルかディレクトリを指定してください: {source}")

    subs: list[Submission] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        m = FOLDER_RE.match(entry.name)
        if not m:
            continue
        sub = Submission(
            student_name=m.group("name"),
            participant_id=m.group("pid"),
            folder_name=entry.name,
            folder_path=entry,
        )
        _select_code_file(sub, expected_filename)
        subs.append(sub)
    if not subs:
        raise SubmissionError(
            "提出フォルダが見つかりませんでした。Moodleの「すべての提出をダウンロード」のzip"
            "（<氏名>_<参加者ID>_assignsubmission_file_ 形式のフォルダ）を指定してください。"
        )
    return subs


def _select_code_file(sub: Submission, expected_filename: str | None = None) -> None:
    """提出フォルダから採点対象ファイルを決める。結果は sub に書き込む。"""
    folder = sub.folder_path

    # 1段だけzip内zipを展開
    for inner_zip in list(folder.rglob("*.zip")):
        try:
            safe_extract_zip(inner_zip, inner_zip.parent / (inner_zip.stem + "_unzipped"))
            sub.flags.append(f"zipファイルで提出されていたため展開しました ({inner_zip.name})")
        except (zipfile.BadZipFile, SubmissionError):
            sub.flags.append(f"zipファイル {inner_zip.name} を展開できませんでした")

    py_files = [p for p in sorted(folder.rglob("*.py")) if p.is_file()]

    chosen: Path | None = None
    if expected_filename:
        for p in py_files:
            if p.name == expected_filename:
                chosen = p
                break
        if chosen is None and py_files:
            sub.flags.append(f"指定ファイル名 {expected_filename} が見つかりません（提出: {', '.join(p.name for p in py_files)}）")
    if chosen is None:
        nonempty = [p for p in py_files if p.stat().st_size > 0]
        if len(nonempty) == 1:
            chosen = nonempty[0]
        elif len(nonempty) > 1:
            chosen = max(nonempty, key=lambda p: p.stat().st_size)
            sub.flags.append(f"複数の.pyファイルが提出されたため {chosen.name} を採点対象にしました")

    # .py がない場合: Pythonとして解析できるテキストを探す
    if chosen is None:
        for p in sorted(folder.rglob("*")):
            if not p.is_file() or p.suffix.lower() in (".zip", ".pdf", ".docx", ".png", ".jpg", ".jpeg"):
                continue
            try:
                text, _, _ = decode_source(p.read_bytes())
            except OSError:
                continue
            if text.strip() and _parses(text):
                chosen = p
                sub.flags.append(f".pyファイルがないため {p.name} を採点対象にしました（提出形式を確認してください）")
                break

    if chosen is None:
        sub.flags.append("採点可能なPythonファイルが見つかりませんでした")
        return

    sub.code_path = chosen
    text, enc, enc_flags = decode_source(chosen.read_bytes())
    sub.code_text = text
    sub.encoding = enc
    sub.flags.extend(enc_flags)
