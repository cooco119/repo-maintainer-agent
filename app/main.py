import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from .config import REPO, SCAN_INTERVAL_MIN
from .db import connect, init_db
from .evaluator import metrics
from .ingest import ingest_issue
from .scanner import scan
from .worker import WorkerPool

pool = WorkerPool()
@asynccontextmanager
async def lifespan(app):
    init_db()
    worker = asyncio.create_task(pool.serve())
    scanner = asyncio.create_task(_scheduled_scan()) if SCAN_INTERVAL_MIN else None
    yield
    worker.cancel()
    if scanner:
        scanner.cancel()

async def _scheduled_scan():
    while True:
        await asyncio.sleep(SCAN_INTERVAL_MIN * 60)
        for task in await scan():
            await pool.enqueue(task)

app = FastAPI(title="Devin Remediator", lifespan=lifespan)

@app.post("/webhook/github")
async def github_webhook(request: Request):
    payload = await request.json()
    if payload.get("issue"):
        issue = payload["issue"]
        action = payload.get("action")
        if action in {"opened", "labeled"}:
            repo = payload.get("repository", {}).get("full_name", REPO)
            labels = [x.get("name", "") for x in issue.get("labels", [])]
            task, created = ingest_issue(repo, issue["number"], issue.get("title", ""), issue.get("body", ""), labels)
            if created: await pool.enqueue(task)
            return {"task_id": task["id"], "created": created}
    if payload.get("pull_request") and payload.get("review"):
        with connect() as db:
            db.execute("INSERT INTO reviews(task_id,action,body,created_at) SELECT id,?,?,datetime('now') FROM tasks WHERE pr_url LIKE ?",
                       (payload["review"].get("state", "").lower(), payload["review"].get("body"), f"%/{payload['pull_request']['number']}"))
        return {"recorded": True}
    return {"ignored": True}

@app.post("/simulate/issue")
async def simulate_issue(data: dict):
    task, created = ingest_issue(data.get("repo", REPO), data.get("issue_number", 1),
                                 data.get("title", "Simulated issue"), data.get("body", "Please fix"),
                                 data.get("labels", []))
    if created: await pool.enqueue(task)
    return {"task": task, "created": created}

@app.post("/scan")
async def scan_route():
    tasks = await scan()
    for task in tasks: await pool.enqueue(task)
    return {"created": len(tasks)}

@app.get("/api/tasks")
def tasks():
    with connect() as db:
        items = []
        for row in db.execute("SELECT * FROM tasks ORDER BY created_at DESC"):
            item = dict(row); item["labels"] = json.loads(item["labels"])
            item["timeline"] = [dict(e) for e in db.execute("SELECT * FROM events WHERE task_id=? ORDER BY id", (row["id"],))]
            items.append(item)
        return items

@app.get("/api/metrics")
def api_metrics(): return metrics()

@app.get("/")
def dashboard(): return FileResponse(Path(__file__).parent.parent / "static" / "index.html")
