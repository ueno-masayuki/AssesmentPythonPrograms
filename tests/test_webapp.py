import time
from pathlib import Path

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PYGRADER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # storageはモジュール読み込み時に初期化されるため、作り直す
    import importlib

    from webapp import main as webapp_main
    importlib.reload(webapp_main)

    from fastapi.testclient import TestClient
    return TestClient(webapp_main.app)


SAVE_PAYLOAD = {
    "title": "テスト課題",
    "description": "合計を出力する",
    "max_grade": 100,
    "weights": {"tests": 0.7, "rubric": 0.3},
    "tests": {"timeout": 3, "cases": [
        {"name": "基本", "stdin": "3\n10 20 30\n", "expected_stdout": "合計: 60\n平均: 20.0\n",
         "match": "trim", "weight": 2},
    ]},
    "rubric": [{"id": "readability", "name": "可読性", "points": 10}],
    "model_answer": (
        "def average(xs):\n    return sum(xs) / len(xs)\n\n"
        "n = int(input())\nnums = list(map(int, input().split()))\n"
        "print(f'合計: {sum(nums)}')\nprint(f'平均: {average(nums)}')\n"
    ),
    "llm": {"model": "claude-sonnet-5-5", "enabled": True},
    "similarity_check": True,
}


def _create_assignment(client) -> str:
    res = client.post("/assignments/new", data={"title": "テスト課題"}, follow_redirects=False)
    assert res.status_code == 303
    slug = res.headers["location"].rsplit("/", 1)[-1]
    res = client.post(f"/api/assignments/{slug}/save", json=SAVE_PAYLOAD)
    assert res.status_code == 200, res.text
    return slug


def test_index(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "課題一覧" in res.text


def test_assignment_crud(client):
    slug = _create_assignment(client)
    res = client.get(f"/assignments/{slug}")
    assert res.status_code == 200
    assert "テスト課題" in res.text

    # 不正な保存はエラーメッセージを返す
    bad = dict(SAVE_PAYLOAD, tests={"cases": [{"name": "x", "match": "bogus", "expected_stdout": "y"}]})
    res = client.post(f"/api/assignments/{slug}/save", json=bad)
    assert res.status_code == 400
    assert "match" in res.json()["detail"]

    res = client.post(f"/assignments/{slug}/delete", follow_redirects=False)
    assert res.status_code == 303
    assert client.get(f"/assignments/{slug}").status_code == 404


def test_check_endpoint(client):
    slug = _create_assignment(client)
    res = client.post(f"/api/assignments/{slug}/check", json={"assignment": SAVE_PAYLOAD})
    assert res.status_code == 200
    results = res.json()["results"]
    assert all(r["status"] == "pass" for r in results)


def test_propose_without_api_key(client):
    slug = _create_assignment(client)
    res = client.post(f"/api/assignments/{slug}/propose",
                      json={"target": "rubric", "assignment": SAVE_PAYLOAD})
    assert res.status_code == 503
    assert "ANTHROPIC_API_KEY" in res.json()["detail"]


def test_grade_flow(client, fixtures: Path):
    slug = _create_assignment(client)

    with (fixtures / "submissions.zip").open("rb") as sub, \
         (fixtures / "worksheet_ja.csv").open("rb") as ws:
        res = client.post(
            f"/assignments/{slug}/grade",
            files={"submissions": ("submissions.zip", sub, "application/zip"),
                   "worksheet": ("worksheet.csv", ws, "text/csv")},
            data={"use_llm": "false", "use_cache": "true"},
            follow_redirects=False,
        )
    assert res.status_code == 303
    run_url = res.headers["location"]

    # ジョブ完了を待つ
    for _ in range(100):
        s = client.get(f"/api{run_url}/status").json()
        if s["status"] in ("done", "error"):
            break
        time.sleep(0.3)
    assert s["status"] == "done", s

    res = client.get(run_url)
    assert res.status_code == 200
    assert "学生別結果" in res.text
    assert "山田 太郎" in res.text

    # ダウンロード3種
    for key, head in [("worksheet", b"\xef\xbb\xbf"), ("feedback_zip", b"PK"), ("report", b"#")]:
        res = client.get(f"{run_url}/download/{key}")
        assert res.status_code == 200, key
        assert res.content.startswith(head), key
