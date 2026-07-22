import asyncio
import re

import httpx

from .config import (
    GITHUB_POLL_INTERVAL_SEC,
    GITHUB_TOKEN,
    REPO,
    TRIGGER_ASSIGNEE,
)
from .db import connect
from .ingest import ingest_issue
from .logging_utils import log_event
from .notifier import notify
from .scanner import scan

TRIAGE_MARKER = "<!-- remediator-triage -->"
_token_login = None


def is_scan_trigger(issue: dict) -> bool:
    title = issue.get("title", "")
    labels = {
        label.get("name", "").lower()
        for label in issue.get("labels", [])
        if isinstance(label, dict)
    }
    return bool(re.search(r"dependency scan", title, re.IGNORECASE) or "scan" in labels)


def triage_decision(issue: dict, assignee: str = "") -> tuple[str, str]:
    """Return auto, explicit, or await along with the human-readable rationale."""
    labels = {
        label.get("name", "").lower()
        for label in issue.get("labels", [])
        if isinstance(label, dict)
    }
    assignees = {
        user.get("login", "").lower()
        for user in issue.get("assignees", [])
        if isinstance(user, dict)
    }
    if "remediate" in labels:
        return "explicit", "remediate label"
    if assignee and assignee.lower() in assignees:
        return "explicit", f"assigned to {assignee}"
    auto_labels = {"security", "dependency", "dependencies", "easy"}
    if labels & auto_labels:
        return "auto", f"{sorted(labels & auto_labels)[0]} label"
    if re.search(r"dependency|vulnerab|deprecat|typo", issue.get("title", ""), re.IGNORECASE):
        return "auto", "low-risk title pattern"
    return "await", "no confidence or explicit assignment"


def _cursor():
    with connect() as db:
        row = db.execute("SELECT value FROM meta WHERE key='github_poll_created_at'").fetchone()
    return row["value"] if row else ""


def _save_cursor(value):
    with connect() as db:
        db.execute(
            "INSERT INTO meta(key,value) VALUES('github_poll_created_at',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (value,),
        )


def _tracked(repo, number):
    with connect() as db:
        return db.execute(
            "SELECT 1 FROM tasks WHERE repo=? AND issue_number=?", (repo, number)
        ).fetchone() is not None


async def _scan_issue(client, pool, issue, correlation_id):
    created = await scan()
    for task in created:
        await pool.enqueue(task)
    summary = f"Dependency scan completed: {len(created)} remediation task(s) created."
    await client.post(
        f"https://api.github.com/repos/{REPO}/issues/{issue['number']}/comments",
        json={"body": summary},
    )
    await client.patch(
        f"https://api.github.com/repos/{REPO}/issues/{issue['number']}",
        json={"state": "closed"},
    )
    await notify(f"🔎 Dependency scan requested by issue #{issue['number']}: {summary}", correlation_id)


async def _has_triage_marker(client, number):
    response = await client.get(
        f"https://api.github.com/repos/{REPO}/issues/{number}/comments",
        params={"per_page": 100},
    )
    return response.is_success and any(
        TRIAGE_MARKER in (comment.get("body") or "") for comment in response.json()
    )


async def _resolve_assignee(client):
    global _token_login
    if TRIGGER_ASSIGNEE:
        return TRIGGER_ASSIGNEE
    if _token_login is None:
        response = await client.get("https://api.github.com/user")
        _token_login = response.json().get("login", "") if response.is_success else ""
    return _token_login


async def _triage_issue(client, pool, issue, assignee, is_new):
    number = issue.get("number")
    if is_scan_trigger(issue):
        if is_new:
            await _scan_issue(client, pool, issue, f"github-poll-{number}")
        return
    body = issue.get("body") or ""
    if "remediator-key:" in body or _tracked(REPO, number):
        return
    decision, reason = triage_decision(issue, assignee)
    if decision in {"auto", "explicit"}:
        task, created = ingest_issue(
            REPO, number, issue.get("title", ""), body,
            [label.get("name", "") for label in issue.get("labels", [])],
        )
        if created:
            await pool.enqueue(task)
            if decision == "auto":
                message = f"📥 Auto-picked up issue #{number} (reason: {reason})."
            else:
                message = f"📥 Picked up issue #{number} (explicitly assigned)."
            await notify(message, task["correlation_id"])
        return
    if await _has_triage_marker(client, number):
        return
    comment = (
        f"{TRIAGE_MARKER}\n"
        f"I think I can handle this. Assign it to {assignee or 'the remediation bot'} "
        "(or add the `remediate` label) and I'll get started."
    )
    response = await client.post(
        f"https://api.github.com/repos/{REPO}/issues/{number}/comments",
        json={"body": comment},
    )
    if response.is_success:
        correlation_id = f"github-poll-{number}"
        log_event("issue_triaged", correlation_id, issue_number=number, reason=reason)
        await notify(
            f"🤔 Issue #{number} triaged: awaiting explicit assignment.",
            correlation_id,
        )


async def poll_once(pool, client=None):
    if not GITHUB_TOKEN:
        return 0
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {GITHUB_TOKEN}"}
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=20, headers=headers)
    try:
        response = await client.get(
            f"https://api.github.com/repos/{REPO}/issues",
            params={"state": "open", "sort": "created", "direction": "asc", "per_page": 100},
        )
        if not response.is_success:
            return 0
        last_seen = _cursor()
        assignee = await _resolve_assignee(client)
        latest = last_seen
        processed = 0
        for issue in response.json():
            created_at = issue.get("created_at", "")
            is_new = not last_seen or created_at > last_seen
            latest = max(latest, created_at)
            if issue.get("pull_request"):
                continue
            await _triage_issue(client, pool, issue, assignee, is_new)
            processed += 1
        if latest:
            _save_cursor(latest)
        return processed
    finally:
        if own_client:
            await client.aclose()


async def github_poll_loop(pool):
    while True:
        try:
            await poll_once(pool)
        except Exception as exc:
            await notify(f"⚠️ GitHub issue poller error: {exc}", "github-poller")
        await asyncio.sleep(GITHUB_POLL_INTERVAL_SEC)
