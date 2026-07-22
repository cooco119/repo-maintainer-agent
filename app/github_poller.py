import asyncio
import re

import httpx

from .config import GITHUB_POLL_INTERVAL_SEC, GITHUB_TOKEN, REPO
from .db import connect
from .ingest import ingest_issue
from .notifier import notify
from .scanner import scan


def is_scan_trigger(issue: dict) -> bool:
    title = issue.get("title", "")
    labels = {
        label.get("name", "").lower()
        for label in issue.get("labels", [])
        if isinstance(label, dict)
    }
    return bool(re.search(r"dependency scan", title, re.IGNORECASE) or "scan" in labels)


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
        processed = 0
        for issue in response.json():
            created_at = issue.get("created_at", "")
            if last_seen and created_at <= last_seen:
                continue
            if issue.get("pull_request"):
                _save_cursor(max(last_seen, created_at))
                last_seen = max(last_seen, created_at)
                continue
            number = issue.get("number")
            if is_scan_trigger(issue):
                await _scan_issue(client, pool, issue, f"github-poll-{number}")
            elif not ("remediator-key:" in (issue.get("body") or "") and _tracked(REPO, number)):
                task, created = ingest_issue(
                    REPO, number, issue.get("title", ""), issue.get("body", ""),
                    [label.get("name", "") for label in issue.get("labels", [])],
                )
                if created:
                    await pool.enqueue(task)
            processed += 1
            _save_cursor(max(last_seen, created_at))
            last_seen = max(last_seen, created_at)
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
