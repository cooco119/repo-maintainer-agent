import asyncio
import os

import httpx

from .logging_utils import log_event


async def notify(message: str, correlation_id: str = ""):
    """Send a teammate-style update without allowing Slack to affect work."""
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        log_event("slack_notify", correlation_id, message=message, mode="fallback")
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(webhook_url, json={"text": message})
            response.raise_for_status()
        return True
    except Exception as exc:
        log_event("slack_notify", correlation_id, message=message, error=str(exc))
        return False


def notify_background(message: str, correlation_id: str = ""):
    """Schedule notification from sync lifecycle code, or log in sync contexts."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log_event("slack_notify", correlation_id, message=message, mode="fallback")
        return None
    task = loop.create_task(notify(message, correlation_id))
    task.add_done_callback(lambda completed: None)
    return task
