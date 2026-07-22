import os
import shlex
import subprocess
import time

from .config import GITHUB_TOKEN, GITHUB_TOKEN_CMD
from .logging_utils import log_event

TOKEN_TTL_SEC = 30 * 60
_cached_token = None
_cached_until = 0.0


def get_github_token():
    """Return a current GitHub token, refreshing command-backed tokens periodically."""
    global _cached_token, _cached_until
    if _cached_token and time.monotonic() < _cached_until:
        return _cached_token
    command = os.getenv("GITHUB_TOKEN_CMD", GITHUB_TOKEN_CMD)
    static_token = os.getenv("GITHUB_TOKEN", GITHUB_TOKEN)
    token = ""
    if command:
        try:
            result = subprocess.run(
                shlex.split(command),
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            token = result.stdout.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            log_event("github_token_refresh", "", error=str(exc), mode="command")
    if not token:
        token = static_token.strip()
    _cached_token = token or None
    _cached_until = time.monotonic() + TOKEN_TTL_SEC if token else 0.0
    return token


def invalidate():
    """Forget the cached token after an authentication failure."""
    global _cached_token, _cached_until
    _cached_token = None
    _cached_until = 0.0


def github_configured():
    return bool(
        os.getenv("GITHUB_TOKEN_CMD", GITHUB_TOKEN_CMD)
        or os.getenv("GITHUB_TOKEN", GITHUB_TOKEN)
    )
