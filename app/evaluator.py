import json
import statistics
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from .config import AUTO_MERGE, GITHUB_TOKEN, HOURS_PER_ISSUE
from .db import connect, now
from .issue_comments import comment_on_issue, completion_comment
from .notifier import notify
from .state import transition


def _pr_api_url(pr_url):
    parts = urlparse(pr_url or "").path.strip("/").split("/")
    if len(parts) >= 4 and parts[-2] == "pull":
        return f"https://api.github.com/repos/{parts[0]}/{parts[1]}/pulls/{parts[-1]}"
    return None


def merge_policy(task, checks, pr_data, auto_merge=AUTO_MERGE):
    """Return (decision, rationale) without performing any GitHub mutations."""
    if not task.get("pr_url"):
        return "FAILED", "pull request URL is missing"
    if not auto_merge:
        return "AWAITING_HUMAN_REVIEW", "auto-merge is disabled"
    if checks is not True:
        return "AWAITING_HUMAN_REVIEW", "checks are not confirmed passing"
    labels = {label.lower() for label in task.get("labels", [])}
    if "security" in labels:
        return "AUTO_MERGE", "security-labeled issue with passing checks"
    changed_files = pr_data.get("changed_files") if pr_data else None
    additions = pr_data.get("additions") if pr_data else None
    deletions = pr_data.get("deletions") if pr_data else None
    if (
        changed_files is not None
        and additions is not None
        and deletions is not None
        and changed_files <= 3
        and additions + deletions <= 50
    ):
        return "AUTO_MERGE", "small PR (<=3 files and <=50 additions/deletions)"
    return "AWAITING_HUMAN_REVIEW", "PR exceeds the small-change merge policy"


async def evaluate_task(task_id):
    with connect() as db:
        task_row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    task = dict(task_row)
    task["labels"] = json.loads(task["labels"])
    checks = None
    pr_exists = bool(task["pr_url"])
    feedback = "checks unavailable"
    pr_data = None
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
                    pr_data = pr_response.json()
                if pr_exists and GITHUB_TOKEN and pr_data:
                    sha = pr_data.get("head", {}).get("sha")
                    checks_response = await client.get(
                        f"{api_url.rsplit('/pulls/', 1)[0]}/commits/{sha}/check-runs"
                    )
                    if checks_response.is_success:
                        runs = checks_response.json().get("check_runs", [])
                        if runs and any(run.get("status") != "completed" for run in runs):
                            checks = None
                            feedback = "checks are still pending"
                        elif runs:
                            checks = all(run.get("conclusion") == "success" for run in runs)
                            feedback = "all checks completed"
                        else:
                            feedback = "no check runs reported"
        except httpx.HTTPError:
            feedback = "GitHub API error; checks unknown"
    score = (0.5 if pr_exists else 0.0) + (0.5 if checks is True else 0.0)
    decision, rationale = merge_policy(task, checks, pr_data)
    merged = False
    if decision == "AUTO_MERGE" and api_url and GITHUB_TOKEN:
        try:
            async with httpx.AsyncClient(timeout=20, headers=headers) as client:
                merge_response = await client.put(
                    f"{api_url}/merge",
                    json={"merge_method": "squash"},
                )
            merged = merge_response.is_success and merge_response.json().get("merged", False)
            if not merged:
                decision = "AWAITING_HUMAN_REVIEW"
                rationale = "auto-merge request was rejected by GitHub"
        except httpx.HTTPError:
            decision = "AWAITING_HUMAN_REVIEW"
            rationale = "auto-merge request failed"
    if score < 0.5:
        decision = "FAILED"
        rationale = "pull request could not be confirmed"
    with connect() as db:
        db.execute(
            "INSERT INTO evals(task_id,checks_passed,judge_score,score,feedback,merge_decision,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (task_id, None if checks is None else int(checks), None, score,
             f"{feedback}; {rationale}", decision, now()),
        )
        eval_row = db.execute(
            "SELECT * FROM evals WHERE task_id=? ORDER BY id DESC LIMIT 1", (task_id,)
        ).fetchone()
    target = "MERGED" if merged else ("FAILED" if decision == "FAILED" else
                                      "AWAITING_HUMAN_REVIEW")
    transition(task_id, target, task["correlation_id"])
    await notify(
        f"📊 Issue #{task['issue_number']} evaluated: score {score:.2f} "
        f"(checks: {'passed' if checks is True else 'unknown'}).",
        task["correlation_id"],
    )
    await comment_on_issue(
        task["repo"],
        task["issue_number"],
        completion_comment(
            task["issue_number"],
            task["pr_url"],
            score,
            checks,
            eval_row["merge_decision"],
            rationale,
            task["session_url"],
            task["created_at"],
        ),
    )
    if merged:
        await notify(
            f"🚀 Auto-merged PR {task['pr_url']} for issue #{task['issue_number']} "
            f"({rationale}).",
            task["correlation_id"],
        )
    elif target == "AWAITING_HUMAN_REVIEW":
        await notify(
            f"👀 PR {task['pr_url']} needs human review ({rationale}).",
            task["correlation_id"],
        )
    else:
        await notify(
            f"❌ Issue #{task['issue_number']} failed after {task['attempts']} attempts.",
            task["correlation_id"],
        )
    return score


def metrics():
    with connect() as db:
        counts = {r["state"]: r["n"] for r in db.execute("SELECT state,count(*) n FROM tasks GROUP BY state")}
        rows = db.execute(
            "SELECT t.*,e.score FROM tasks t LEFT JOIN evals e ON e.task_id=t.id"
        ).fetchall()
        remediated = [r for r in rows if r["state"] in {"DONE", "MERGED", "AWAITING_HUMAN_REVIEW"}]
        first_pass = [r for r in remediated if r["attempts"] == 1]
        ttrs = [
            (datetime.fromisoformat(r["updated_at"]) - datetime.fromisoformat(r["created_at"])).total_seconds()
            for r in remediated
        ]
        difficulty = {}
        for label in ("easy", "medium", "hard"):
            subset = [r for r in rows if label in json.loads(r["labels"])]
            difficulty[label] = sum(r["state"] in {"DONE", "MERGED", "AWAITING_HUMAN_REVIEW"}
                                    for r in subset) / len(subset) if subset else 0
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
            "first_pass_success_rate": len(first_pass) / len(remediated) if remediated else 0,
            "success_by_difficulty": difficulty,
            "throughput_per_day": len(remediated) / days,
            "avg_eval_score": statistics.mean(
                [r["score"] for r in rows if r["score"] is not None]
            ) if any(r["score"] is not None for r in rows) else 0,
            "blocked_or_escalated": sum(
                r["state"] == "BLOCKED" or r["blocked_escalated"] for r in rows
            ),
            "human_feedback_approval_rate": feedback_rate,
            "engineer_hours_reclaimed": len(remediated) * HOURS_PER_ISSUE,
        }
