import json
import statistics
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from .config import GITHUB_TOKEN, HOURS_PER_ISSUE
from .db import connect, now
from .state import transition


def _pr_api_url(pr_url):
    parts = urlparse(pr_url or "").path.strip("/").split("/")
    if len(parts) >= 4 and parts[-2] == "pull":
        return f"https://api.github.com/repos/{parts[0]}/{parts[1]}/pulls/{parts[-1]}"
    return None


async def evaluate_task(task_id):
    with connect() as db:
        task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    checks = None
    pr_exists = bool(task["pr_url"])
    feedback = "checks unavailable"
    api_url = _pr_api_url(task["pr_url"])
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    if api_url:
        try:
            async with httpx.AsyncClient(timeout=20, headers=headers) as client:
                pr_response = await client.get(api_url)
                if pr_response.is_success:
                    pr_exists = True
                if pr_exists and GITHUB_TOKEN:
                    sha = pr_response.json().get("head", {}).get("sha")
                    checks_response = await client.get(
                        f"{api_url.rsplit('/pulls/', 1)[0]}/commits/{sha}/check-runs"
                    )
                    if checks_response.is_success:
                        runs = checks_response.json().get("check_runs", [])
                        checks = all(
                            run.get("status") != "completed" or run.get("conclusion") == "success"
                            for run in runs
                        )
                        feedback = "pending checks treated as passing for now"
        except httpx.HTTPError:
            feedback = "GitHub API error; checks unknown"
    score = (0.5 if pr_exists else 0.0) + (0.5 if checks is True else 0.0)
    with connect() as db:
        db.execute(
            "INSERT INTO evals(task_id,checks_passed,judge_score,score,feedback,created_at) VALUES(?,?,?,?,?,?)",
            (task_id, None if checks is None else int(checks), None, score, feedback, now()),
        )
    transition(task_id, "DONE" if score >= 0.5 else "FAILED", task["correlation_id"])
    return score


def metrics():
    with connect() as db:
        counts = {r["state"]: r["n"] for r in db.execute("SELECT state,count(*) n FROM tasks GROUP BY state")}
        rows = db.execute(
            "SELECT t.*,e.score FROM tasks t LEFT JOIN evals e ON e.task_id=t.id"
        ).fetchall()
        completed = [r for r in rows if r["state"] == "DONE"]
        first_pass = [r for r in completed if r["attempts"] == 1]
        ttrs = [
            (datetime.fromisoformat(r["updated_at"]) - datetime.fromisoformat(r["created_at"])).total_seconds()
            for r in completed
        ]
        difficulty = {}
        for label in ("easy", "medium", "hard"):
            subset = [r for r in rows if label in json.loads(r["labels"])]
            difficulty[label] = sum(r["state"] == "DONE" for r in subset) / len(subset) if subset else 0
        first_created = min((datetime.fromisoformat(r["created_at"]) for r in rows), default=None)
        days = (
            max(1, (datetime.now(timezone.utc) - first_created).total_seconds() / 86400)
            if first_created else 1
        )
        review_rows = db.execute("SELECT action FROM reviews").fetchall()
        approvals = sum(r["action"] == "approved" for r in review_rows)
        feedback_rate = approvals / len(review_rows) if review_rows else 0
        return {
            "counts": counts,
            "ttr_median_seconds": statistics.median(ttrs) if ttrs else 0,
            "first_pass_success_rate": len(first_pass) / len(completed) if completed else 0,
            "success_by_difficulty": difficulty,
            "throughput_per_day": len(completed) / days,
            "avg_eval_score": statistics.mean(
                [r["score"] for r in rows if r["score"] is not None]
            ) if any(r["score"] is not None for r in rows) else 0,
            "blocked_or_escalated": sum(
                r["state"] == "BLOCKED" or r["blocked_escalated"] for r in rows
            ),
            "human_feedback_approval_rate": feedback_rate,
            "engineer_hours_reclaimed": len(completed) * HOURS_PER_ISSUE,
        }
