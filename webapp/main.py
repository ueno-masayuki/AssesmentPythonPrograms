"""WebUI (FastAPI)。課題の登録・編集・提案、採点実行、結果ダウンロード。

起動: python -m pygrader serve  （127.0.0.1にバインド。認証はないためローカル専用）
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pygrader import llm as llm_mod
from pygrader import proposals
from pygrader.config import Assignment, ConfigError, assignment_from_dict
from pygrader.pipeline import check_model_answer
from pygrader.runner import run_tests

from .jobs import JobManager, load_summary
from .storage import Storage

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="pygrader")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

storage = Storage(Path(os.environ["PYGRADER_DATA_DIR"]) if os.environ.get("PYGRADER_DATA_DIR") else None)
jobs = JobManager()


def _assignment_or_404(slug: str) -> Assignment:
    try:
        if not storage.exists(slug):
            raise HTTPException(status_code=404, detail="課題が見つかりません")
        return storage.load(slug)
    except ConfigError as e:
        raise HTTPException(status_code=400, detail=f"課題設定の読み込みに失敗しました: {e}") from e


def _parse_assignment(data: dict) -> Assignment:
    try:
        return assignment_from_dict(data)
    except (ConfigError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ---------------------------------------------------------------------------
# 課題一覧・CRUD
# ---------------------------------------------------------------------------

@app.get("/")
async def index(request: Request):
    assignments = storage.list_assignments()
    runs = storage.list_runs()[:20]
    return templates.TemplateResponse(request, "index.html", {
        "assignments": assignments,
        "runs": runs,
        "llm_available": llm_mod.llm_available(),
    })


@app.post("/assignments/new")
async def create_assignment(title: str = Form(...)):
    title = title.strip() or "新しい課題"
    slug = storage.slugify(title)
    a = Assignment(title=title, description="", tests=[], rubric=[],
                   weight_tests=0.7, weight_rubric=0.3)
    # validate()は tests/rubric 空を許さないため、保存だけ直接行う
    a.save(storage.assignment_path(slug))
    return RedirectResponse(f"/assignments/{slug}", status_code=303)


@app.get("/assignments/{slug}")
async def edit_assignment(request: Request, slug: str):
    a = _assignment_or_404(slug)
    return templates.TemplateResponse(request, "assignment_edit.html", {
        "slug": slug,
        "assignment_dict": a.to_dict(),
        "llm_available": llm_mod.llm_available(),
    })


@app.post("/api/assignments/{slug}/save")
async def save_assignment(slug: str, request: Request):
    if not storage.exists(slug):
        raise HTTPException(status_code=404, detail="課題が見つかりません")
    data = await request.json()
    a = _parse_assignment(data)
    storage.save(slug, a)
    return {"ok": True}


@app.post("/assignments/{slug}/delete")
async def delete_assignment(slug: str):
    storage.delete(slug)
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# 提案機能・動作確認
# ---------------------------------------------------------------------------

@app.post("/api/assignments/{slug}/propose")
async def propose(slug: str, request: Request):
    """現在の編集中の内容（未保存可）に基づいて提案を生成する。"""
    body = await request.json()
    target = body.get("target")
    a = _parse_for_tools(body.get("assignment") or {})
    try:
        if target == "model_answer":
            p = proposals.propose_model_answer(a)
            result: dict = {"code": p.code, "explanation": p.explanation_ja}
            # 登録済みテストがあれば提案コードを即実行して合否を付ける
            if a.tests:
                outcome = run_tests(p.code, a, filename=a.expected_filename or "main.py")
                result["test_results"] = [
                    {"name": r.case.name, "status": r.status, "detail": r.detail}
                    for r in outcome.results
                ]
            return result
        if target == "rubric":
            p = proposals.propose_rubric(a)
            return {"criteria": [
                {"id": c.id, "name": c.name_ja, "points": c.points, "description": c.description_ja}
                for c in p.criteria
            ]}
        if target == "tests":
            p = proposals.propose_tests(a)
            return {"cases": [
                {"name": c.name_ja, "stdin": c.stdin, "expected_stdout": c.expected_stdout,
                 "match": c.match, "weight": c.weight}
                for c in p.cases
            ]}
    except llm_mod.LLMUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    raise HTTPException(status_code=400, detail="target は model_answer / rubric / tests のいずれかです")


@app.post("/api/assignments/{slug}/check")
async def check(slug: str, request: Request):
    """回答例に全テストを実行する（動作確認）。未保存の編集内容を受け取る。"""
    body = await request.json()
    a = _parse_for_tools(body.get("assignment") or {})
    try:
        outcome = check_model_answer(a)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"results": [
        {"name": r.case.name, "status": r.status, "detail": r.detail, "stdout": r.stdout[:500]}
        for r in outcome.results
    ]}


def _parse_for_tools(data: dict) -> Assignment:
    """提案・動作確認用: tests/rubricが空でも許容する緩い解析。"""
    data = dict(data)
    data.setdefault("title", "untitled")
    try:
        return assignment_from_dict(data)
    except ConfigError as e:
        # tests/rubric両方空のときのvalidateエラーだけ救済する
        if "少なくとも一方" in str(e):
            data["rubric"] = [{"id": "placeholder", "name": "仮", "points": 1}]
            a = assignment_from_dict(data)
            a.rubric = []
            return a
        raise HTTPException(status_code=400, detail=str(e)) from e


# ---------------------------------------------------------------------------
# 採点実行
# ---------------------------------------------------------------------------

@app.get("/assignments/{slug}/grade")
async def grade_form(request: Request, slug: str):
    a = _assignment_or_404(slug)
    return templates.TemplateResponse(request, "grade.html", {
        "slug": slug,
        "assignment": a,
        "llm_available": llm_mod.llm_available(),
    })


@app.post("/assignments/{slug}/grade")
async def grade_start(slug: str,
                      submissions: UploadFile,
                      worksheet: UploadFile | None = None,
                      use_llm: bool = Form(True),
                      use_cache: bool = Form(True)):
    a = _assignment_or_404(slug)
    run_id, out_dir = storage.new_run_dir(slug)

    uploads = out_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    sub_path = uploads / "submissions.zip"
    with sub_path.open("wb") as f:
        shutil.copyfileobj(submissions.file, f)

    ws_path = None
    if worksheet is not None and worksheet.filename:
        ws_path = uploads / "worksheet.csv"
        with ws_path.open("wb") as f:
            shutil.copyfileobj(worksheet.file, f)

    jobs.start(run_id, a, sub_path, out_dir, ws_path, use_llm=use_llm, use_cache=use_cache)
    return RedirectResponse(f"/runs/{run_id}", status_code=303)


@app.get("/api/runs/{slug}/{stamp}/status")
async def run_status(slug: str, stamp: str):
    run_id = f"{slug}/{stamp}"
    job = jobs.get(run_id)
    if job is not None:
        with job.lock:
            return {"status": job.status, "done": job.done, "total": job.total,
                    "current": job.current, "error": job.error}
    out_dir = storage.run_dir(run_id)
    if (out_dir / "summary.json").exists():
        return {"status": "done"}
    if (out_dir / "error.txt").exists():
        return {"status": "error", "error": (out_dir / "error.txt").read_text(encoding="utf-8").splitlines()[-1]}
    raise HTTPException(status_code=404, detail="採点ジョブが見つかりません")


@app.get("/runs/{slug}/{stamp}")
async def run_page(request: Request, slug: str, stamp: str):
    run_id = f"{slug}/{stamp}"
    out_dir = storage.run_dir(run_id)
    if not out_dir.exists():
        raise HTTPException(status_code=404, detail="採点結果が見つかりません")
    summary = load_summary(out_dir)
    report_md = ""
    if summary and (out_dir / "report.md").exists():
        report_md = (out_dir / "report.md").read_text(encoding="utf-8")
    return templates.TemplateResponse(request, "run_result.html", {
        "run_id": run_id, "slug": slug, "stamp": stamp,
        "summary": summary, "report_md": report_md,
    })


_DOWNLOADS = {
    "worksheet": ("grading_worksheet_filled.csv", "text/csv"),
    "feedback_zip": ("feedback_files.zip", "application/zip"),
    "report": ("report.md", "text/markdown"),
}


@app.get("/runs/{slug}/{stamp}/download/{key}")
async def download(slug: str, stamp: str, key: str):
    if key not in _DOWNLOADS:
        raise HTTPException(status_code=404, detail="不明なファイルです")
    filename, media_type = _DOWNLOADS[key]
    path = storage.run_dir(f"{slug}/{stamp}") / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="ファイルがありません")
    return FileResponse(path, media_type=media_type, filename=f"{slug}_{stamp}_{filename}")


@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    # APIはJSON、ページ遷移は簡易エラーページ
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return templates.TemplateResponse(request, "error.html",
                                      {"detail": exc.detail, "status": exc.status_code},
                                      status_code=exc.status_code)
