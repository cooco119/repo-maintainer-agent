import re

import httpx
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from .config import GITHUB_TOKEN, REPO, SLACK_APP_TOKEN, SLACK_BOT_TOKEN
from .db import connect
from .evaluator import metrics
from .ingest import ingest_issue
from .notifier import set_bot_client
from .scanner import scan


def route_message(text):
    """Parse teammate text into a side-effect-free command description."""
    value = re.sub(r"<@[^>]+>", "", text or "").strip()
    lowered = value.lower()
    if lowered == "status":
        return {"action": "status"}
    if lowered == "report":
        return {"action": "report"}
    if lowered == "scan":
        return {"action": "scan"}
    match = re.fullmatch(r"(?:issue\s+)?#(\d+)", lowered)
    if match:
        return {"action": "issue", "issue_number": int(match.group(1))}
    match = re.fullmatch(r"remediate\s+(?:(\S+)#)?#?(\d+)", lowered)
    if match:
        return {"action": "remediate", "repo": match.group(1) or REPO,
                "issue_number": int(match.group(2))}
    return {"action": "help"}


def _task_summary(task):
    links = []
    if task["pr_url"]:
        links.append(f"PR: {task['pr_url']}")
    if task["session_url"]:
        links.append(f"session: {task['session_url']}")
    return (
        f"Issue #{task['issue_number']} is {task['state'].lower()} — {task['title']}\n"
        + ("\n".join(links) if links else "No links yet.")
    )


def create_app(pool):
    slack_app = AsyncApp(token=SLACK_BOT_TOKEN)

    async def respond(body, say):
        command = route_message(body.get("event", {}).get("text", ""))
        action = command["action"]
        if action == "status":
            values = metrics()
            with connect() as db:
                active = db.execute(
                    "SELECT issue_number,title,session_url FROM tasks "
                    "WHERE state IN ('WORKING','BLOCKED') ORDER BY updated_at DESC"
                ).fetchall()
            active_text = "\n".join(
                f"#{row['issue_number']} {row['title']} — {row['session_url'] or 'no link'}"
                for row in active
            ) or "No active sessions."
            counts = ", ".join(f"{key}: {value}" for key, value in values["counts"].items())
            await say(f"Here’s the board: {counts}\nActive sessions:\n{active_text}")
        elif action == "report":
            values = metrics()
            await say(
                "📈 Daily report — "
                f"TTR median {values['ttr_median_seconds']:.0f}s, "
                f"first-pass {values['first_pass_success_rate']:.0%}, "
                f"{values['engineer_hours_reclaimed']:.1f} hours reclaimed."
            )
        elif action == "issue":
            with connect() as db:
                task = db.execute(
                    "SELECT * FROM tasks WHERE issue_number=? ORDER BY id DESC LIMIT 1",
                    (command["issue_number"],),
                ).fetchone()
                events = db.execute(
                    "SELECT event_type,created_at FROM events WHERE task_id=? ORDER BY id",
                    (task["id"],),
                ).fetchall() if task else []
            if not task:
                await say(f"I couldn't find issue #{command['issue_number']} in the queue.")
            else:
                timeline = "\n".join(f"• {row['event_type']} ({row['created_at']})" for row in events)
                await say(_task_summary(task) + f"\nTimeline:\n{timeline}")
        elif action == "scan":
            created = await scan()
            for task in created:
                await pool.enqueue(task)
            await say(f"🔍 Scan complete — queued {len(created)} new finding(s).")
        elif action == "remediate":
            task = await _remediate(command["repo"], command["issue_number"], pool)
            if task is None:
                await say(f"Issue {command['repo']}#{command['issue_number']} is already tracked.")
            else:
                await say(f"🔧 Got it — queued {command['repo']}#{command['issue_number']}.")
        else:
            await say("Try `status`, `report`, `issue #N`, `scan`, or `remediate owner/repo#N`.")

    @slack_app.event("app_mention")
    async def mention_handler(body, say):
        await respond(body, say)

    @slack_app.event("message")
    async def message_handler(body, say):
        event = body.get("event", {})
        if event.get("channel_type") == "im" and not event.get("subtype"):
            await respond(body, say)

    set_bot_client(slack_app.client)
    return slack_app


async def _remediate(repo, issue_number, pool):
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        response = await client.get(f"https://api.github.com/repos/{repo}/issues/{issue_number}")
        if not response.is_success:
            return None
        issue = response.json()
    task, created = ingest_issue(
        repo, issue_number, issue.get("title", ""), issue.get("body", ""),
        [label.get("name", "") for label in issue.get("labels", [])],
    )
    if created:
        await pool.enqueue(task)
        return task
    return None


async def start_socket_mode(pool):
    if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
        return None
    try:
        handler = AsyncSocketModeHandler(create_app(pool), SLACK_APP_TOKEN)
        await handler.start_async()
    except Exception:
        return None
