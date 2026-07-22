import os
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
