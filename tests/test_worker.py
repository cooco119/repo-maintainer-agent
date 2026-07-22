import os
import asyncio
import time
os.environ["DB_PATH"] = "/tmp/devin-remediator-worker-test.db"
os.environ["DRY_RUN"] = "1"
os.environ["POLL_INTERVAL"] = "0"
import pytest
import app.worker
from app.db import init_db, connect
from app.ingest import ingest_issue
from app.worker import WorkerPool

@pytest.mark.asyncio
async def test_dry_run_happy_path():
    app.worker.POLL_INTERVAL = 0
    init_db()
    with connect() as db:
        db.executescript("DELETE FROM evals; DELETE FROM reviews; DELETE FROM events; DELETE FROM tasks;")
    task, _ = ingest_issue("x/y", 3, "title", "body")
    await WorkerPool().run_one(task)
    with connect() as db:
        assert db.execute("SELECT state FROM tasks WHERE id=?", (task["id"],)).fetchone()["state"] == "DONE"


@pytest.mark.asyncio
async def test_worker_pool_runs_tasks_in_parallel():
    init_db()
    with connect() as db:
        db.executescript("DELETE FROM evals; DELETE FROM reviews; DELETE FROM events; DELETE FROM tasks;")
    pool = WorkerPool()
    tasks = [
        ingest_issue("x/y", issue, f"title {issue}", f"body {issue}")[0]
        for issue in range(10, 13)
    ]
    for task in tasks:
        await pool.enqueue(task)
    server = asyncio.create_task(pool.serve())
    for _ in range(20):
        await asyncio.sleep(0.05)
        with connect() as db:
            states = [row["state"] for row in db.execute("SELECT state FROM tasks ORDER BY id")]
        if states == ["DONE", "DONE", "DONE"]:
            break
    server.cancel()
    with connect() as db:
        states = [row["state"] for row in db.execute("SELECT state FROM tasks ORDER BY id")]
    assert states == ["DONE", "DONE", "DONE"]


@pytest.mark.asyncio
async def test_worker_resumes_existing_session():
    init_db()
    with connect() as db:
        db.executescript("DELETE FROM evals; DELETE FROM reviews; DELETE FROM events; DELETE FROM tasks;")
    task, _ = ingest_issue("x/y", 13, "resumable", "body")
    session_id = "dry-resume-session"
    with connect() as db:
        db.execute(
            "UPDATE tasks SET state='WORKING',session_id=?,session_url=?,attempts=1 WHERE id=?",
            (session_id, "http://dry-run.local/session/dry-resume-session", task["id"]),
        )
    pool = WorkerPool()
    pool.client.sessions[session_id] = {"started": time.monotonic() - 1, "messages": []}
    await pool.run_one({**task, "state": "WORKING", "session_id": session_id,
                        "session_url": "http://dry-run.local/session/dry-resume-session"})
    with connect() as db:
        row = db.execute("SELECT state,attempts FROM tasks WHERE id=?", (task["id"],)).fetchone()
        assert row["state"] == "DONE"
        assert row["attempts"] == 1
        assert db.execute(
            "SELECT 1 FROM events WHERE task_id=? AND event_type='TASK_RESUMED'", (task["id"],)
        ).fetchone()
