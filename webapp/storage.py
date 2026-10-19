"""課題YAMLと採点結果（runs）のディスク管理。

data/
├── assignments/<slug>.yaml      # 登録済み課題
└── runs/<slug>/<run_id>/        # 採点結果一式
"""

from __future__ import annotations

import datetime
import re
import unicodedata
from pathlib import Path

from pygrader.config import Assignment, load_assignment

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class Storage:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self.assignments_dir = self.data_dir / "assignments"
        self.runs_dir = self.data_dir / "runs"
        self.assignments_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    # ---- 課題 -----------------------------------------------------------

    def slugify(self, title: str) -> str:
        base = unicodedata.normalize("NFKC", title).strip()
        base = re.sub(r"[^\w\-]+", "-", base).strip("-").lower() or "assignment"
        slug = base
        i = 2
        while (self.assignments_dir / f"{slug}.yaml").exists():
            slug = f"{base}-{i}"
            i += 1
        return slug

    def assignment_path(self, slug: str) -> Path:
        if not re.fullmatch(r"[\w\-]+", slug):
            raise ValueError(f"不正な課題IDです: {slug!r}")
        return self.assignments_dir / f"{slug}.yaml"

    def list_assignments(self) -> list[tuple[str, Assignment]]:
        items = []
        for p in sorted(self.assignments_dir.glob("*.yaml")):
            try:
                items.append((p.stem, load_assignment(p)))
            except Exception:
                continue  # 壊れたファイルは一覧から除外（編集画面では開けない）
        return items

    def load(self, slug: str) -> Assignment:
        return load_assignment(self.assignment_path(slug))

    def save(self, slug: str, assignment: Assignment) -> None:
        assignment.save(self.assignment_path(slug))

    def delete(self, slug: str) -> None:
        self.assignment_path(slug).unlink(missing_ok=True)

    def exists(self, slug: str) -> bool:
        return self.assignment_path(slug).exists()

    # ---- 採点結果 --------------------------------------------------------

    def new_run_dir(self, slug: str) -> tuple[str, Path]:
        run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        d = self.runs_dir / slug / run_id
        d.mkdir(parents=True, exist_ok=True)
        return f"{slug}/{run_id}", d

    def run_dir(self, run_id: str) -> Path:
        slug, _, stamp = run_id.partition("/")
        if not re.fullmatch(r"[\w\-]+", slug) or not re.fullmatch(r"[\w\-]+", stamp):
            raise ValueError(f"不正なrun IDです: {run_id!r}")
        return self.runs_dir / slug / stamp

    def list_runs(self, slug: str | None = None) -> list[str]:
        runs = []
        dirs = [self.runs_dir / slug] if slug else sorted(self.runs_dir.iterdir()) if self.runs_dir.exists() else []
        for adir in dirs:
            if not adir.is_dir():
                continue
            for rdir in sorted(adir.iterdir(), reverse=True):
                if rdir.is_dir():
                    runs.append(f"{adir.name}/{rdir.name}")
        return runs
