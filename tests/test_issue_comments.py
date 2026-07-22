from datetime import datetime, timezone

import pytest

import app.issue_comments as issue_comments
from app.issue_comments import completion_comment, failure_comment, start_comment


def test_start_comment_contains_plan_and_branch():
    body = start_comment(42, "https://devin.ai/session/42")
    assert "Remediation started" in body
    assert "`remediator/issue-42`" in body
    assert "Run relevant lint/tests" in body


def test_completion_comment_contains_eval_and_ttr():
    body = completion_comment(
        42,
        "https://github.com/acme/repo/pull/7",
        1.0,
        True,
        "AUTO_MERGE",
        "small PR",
        "https://devin.ai/session/42",
        "2024-01-01T00:00:00+00:00",
        datetime(2024, 1, 1, 0, 12, tzinfo=timezone.utc),
    )
    assert "PR: https://github.com/acme/repo/pull/7" in body
    assert "Eval score: 1.00 (checks: passed)" in body
    assert "Merge decision: auto-merged (small PR)" in body
    assert "Time to remediation: 12m" in body


def test_failure_comment_contains_attempts_and_session():
    body = failure_comment(42, 3, "https://devin.ai/session/42")
    assert "failed after 3 attempts" in body
    assert "https://devin.ai/session/42" in body


@pytest.mark.asyncio
async def test_comment_on_issue_uses_injected_client(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

    class Client:
        def __init__(self):
            self.calls = []

        async def post(self, url, json):
            self.calls.append((url, json))
            return Response()

    client = Client()
    monkeypatch.setattr(issue_comments, "GITHUB_TOKEN", "test-token")
    assert await issue_comments.comment_on_issue("acme/repo", 42, "hello", client) is True
    assert client.calls == [
        (
            "https://api.github.com/repos/acme/repo/issues/42/comments",
            {"body": "hello"},
        )
    ]
