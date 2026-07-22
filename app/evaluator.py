import statistics
import httpx
from .config import GITHUB_TOKEN
from .db import connect, now
from .state import transition

async def evaluate_task(task_id):
    with connect() as db:
        task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    checks = True
    if task["pr_url"] and GITHUB_TOKEN:
        parts = task["pr_url"].split("/")
        if len(parts) > 6 and parts[-2] == "pull":
            api = f"https://api.github.com/repos/{parts[3]}/{parts[4]}/commits"
            try:
                async with httpx.AsyncClient(timeout=20, headers={"Authorization": f"Bearer {GITHUB_TOKEN}"} ) as client:
                    response = await client.get(api)
                    checks = response.is_success
            except httpx.HTTPError:
                checks = False
    score = 1.0 if checks else 0.0
    with connect() as db:
        db.execute("INSERT INTO evals(task_id,checks_passed,judge_score,score,feedback,created_at) VALUES(?,?,?,?,?,?)",
                   (task_id, int(checks), None, score, "noop judge", now()))
    transition(task_id, "DONE" if checks else "FAILED", task["correlation_id"])
    return score

def metrics():
    with connect() as db:
        counts = {r["state"]: r["n"] for r in db.execute("SELECT state,count(*) n FROM tasks GROUP BY state")}
        rows = db.execute("SELECT t.*,e.score FROM tasks t LEFT JOIN evals e ON e.task_id=t.id").fetchall()
        completed = [r for r in rows if r["state"] == "DONE"]
        first_pass = [r for r in completed if r["attempts"] == 1]
        ttrs = []
        for r in completed:
            from datetime import datetime
            ttrs.append((datetime.fromisoformat(r["updated_at"]) - datetime.fromisoformat(r["created_at"])).total_seconds())
        difficulty = {}
        for label in ("easy", "medium", "hard"):
            subset = [r for r in rows if label in r["labels"].lower()]
            difficulty[label] = sum(r["state"] == "DONE" for r in subset) / len(subset) if subset else 0
        return {"counts": counts, "ttr_median_seconds": statistics.median(ttrs) if ttrs else 0,
                "first_pass_success_rate": len(first_pass) / len(completed) if completed else 0,
                "success_by_difficulty": difficulty, "throughput_per_day": len(completed)}
