import os

DB_PATH = os.getenv("DB_PATH", "remediator.db")
DEVIN_API_KEY = os.getenv("DEVIN_API_KEY", "")
DEVIN_BASE_URL = os.getenv("DEVIN_BASE_URL", "https://api.devin.ai/v1")
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"
MAX_PARALLEL_SESSIONS = int(os.getenv("MAX_PARALLEL_SESSIONS", "3"))
SCAN_INTERVAL_MIN = int(os.getenv("SCAN_INTERVAL_MIN", "0"))
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
REPO = os.getenv("REPO", "cooco119/superset")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "30"))
MAX_ISSUES_PER_SCAN = int(os.getenv("MAX_ISSUES_PER_SCAN", "3"))
HOURS_PER_ISSUE = float(os.getenv("HOURS_PER_ISSUE", "4.0"))
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN", "")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "")
AUTO_MERGE = os.getenv("AUTO_MERGE", "0") == "1"
GITHUB_POLL_INTERVAL_SEC = int(os.getenv("GITHUB_POLL_INTERVAL_SEC", "30"))
