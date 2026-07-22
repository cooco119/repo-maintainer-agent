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
