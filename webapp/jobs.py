"""採点ジョブのバックグラウンド実行と進捗管理。

ローカル単一ユーザー前提のため、スレッド + インメモリレジストリで十分。
結果はディスク(runs/)へ永続化され、サーバー再起動後も結果ページは再構成できる。
"""

from __future__ import annotations

import json
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from pygrader.config import Assignment
from pygrader.pipeline import GradeRun, grade


@dataclass
class Job:
    run_id: str
    out_dir: Path
    status: str = "running"          # running / done / error
    done: int = 0
    total: int = 0
    current: str = ""
    error: str = ""
    run: GradeRun | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def get(self, run_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(run_id)

    def start(
        self,
        run_id: str,
        assignment: Assignment,
        submissions_path: Path,
        out_dir: Path,
        worksheet_path: Path | None,
        use_llm: bool,
        use_cache: bool,
    ) -> Job:
        job = Job(run_id=run_id, out_dir=out_dir)
        with self._lock:
            self._jobs[run_id] = job

        def progress(done: int, total: int, name: str) -> None:
            with job.lock:
                job.done, job.total, job.current = done, total, name

        def worker() -> None:
            try:
                run = grade(
                    assignment,
                    submissions_path=submissions_path,
                    worksheet_path=worksheet_path,
                    out_dir=out_dir,
                    use_llm=use_llm,
                    use_cache=use_cache,
                    progress=progress,
                )
                _persist_summary(run, out_dir, run_id)
                with job.lock:
                    job.run = run
                    job.status = "done"
            except Exception as e:  # ジョブ内の例外はUIに表示する
                with job.lock:
                    job.status = "error"
                    job.error = f"{type(e).__name__}: {e}"
                (out_dir / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")

        threading.Thread(target=worker, daemon=True).start()
        return job


def _persist_summary(run: GradeRun, out_dir: Path, run_id: str) -> None:
    """結果ページの再構成に使うサマリをJSONで保存する。"""
    data = {
        "run_id": run_id,
        "title": run.assignment.title,
        "timestamp": run.timestamp,
        "max_grade": run.max_grade,
        "llm_used": run.llm_used,
        "warnings": run.warnings,
        "unmatched_worksheet_rows": run.unmatched_worksheet_rows,
        "outputs": {k: p.name for k, p in run.outputs.items()},
        "students": [
            {
                "name": r.submission.student_name,
                "participant_id": r.submission.participant_id,
                "grade": r.score.final_grade,
                "tests": (f"{r.outcome.passed_count}/{len(r.outcome.results)}"
                          if r.outcome and r.outcome.results else "-"),
                "rubric": (f"{r.evaluation.rubric_ratio * 100:.0f}%" if r.evaluation else "-"),
                "flags": r.flags(),
            }
            for r in run.results
        ],
    }
    (out_dir / "summary.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load_summary(out_dir: Path) -> dict | None:
    p = out_dir / "summary.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))
