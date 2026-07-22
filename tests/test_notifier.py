import os

os.environ.pop("SLACK_WEBHOOK_URL", None)

import pytest

from app.notifier import notify


@pytest.mark.asyncio
async def test_notify_without_webhook_uses_fallback(caplog):
    assert await notify("demo notification", "test-correlation") is False
    assert "slack_notify" in caplog.text
