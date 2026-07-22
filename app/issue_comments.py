from datetime import datetime, timezone

import httpx

from .gh_token import get_github_token, invalidate
from .logging_utils import log_event


def start_comment(issue_number, session_url):
    return (
        f"🤖 **Remediation started** — session: {session_url or 'pending'}\n\n"
        "**Plan:**\n"
        "1. Reproduce/analyze the issue\n"
        "2. Implement a minimal safe fix on branch "
        f"`remediator/issue-{issue_number}`\n"
        "3. Run relevant lint/tests\n"
        "4. Open a PR referencing this issue\n\n"
        "I'll report back here when done."
    )


def completion_comment(
    issue_number,
    pr_url,
    score,
    checks,
    merge_decision,
    rationale,
    session_url,
    created_at,
    completed_at=None,
):
    completed_at = completed_at or datetime.now(timezone.utc)
    created = datetime.fromisoformat(created_at)
    minutes = max(0, round((completed_at - created).total_seconds() / 60))
    decision = {
        "AUTO_MERGE": "auto-merged",
        "AWAITING_HUMAN_REVIEW": "awaiting human review",
    }.get(merge_decision, merge_decision or "unknown")
    check_text = "passed" if checks is True else "unknown"
    return (
        "✅ **Remediation complete**\n"
        f"- PR: {pr_url or 'not available'}\n"
        f"- Eval score: {score:.2f} (checks: {check_text})\n"
        f"- Merge decision: {decision} ({rationale})\n"
        f"- Session: {session_url or 'not available'}\n"
        f"- Time to remediation: {minutes}m"
    )


def failure_comment(issue_number, attempts, session_url):
    return (
        f"❌ Remediation failed after {attempts} attempts — a human should take a look. "
        f"Session: {session_url or 'not available'}"
    )


async def comment_on_issue(repo, number, body, client=None):
    """Post a GitHub issue comment, degrading to a structured log on failure."""
    correlation_id = f"github-issue-{repo}#{number}"
    token = get_github_token()
    if not token:
        log_event("github_issue_comment", correlation_id, repo=repo, number=number,
                  body=body, mode="skipped")
        return False
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(
            timeout=20,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
            },
        )
    try:
        response = await client.post(
            f"https://api.github.com/repos/{repo}/issues/{number}/comments",
            json={"body": body},
        )
        if response.status_code == 401:
            invalidate()
        response.raise_for_status()
        return True
    except Exception as exc:
        log_event(
            "github_issue_comment",
            correlation_id,
            repo=repo,
            number=number,
            error=str(exc),
        )
        return False
    finally:
        if own_client:
            try:
                await client.aclose()
            except Exception as exc:
                log_event(
                    "github_issue_comment",
                    correlation_id,
                    repo=repo,
                    number=number,
                    error=str(exc),
                    phase="close",
                )
