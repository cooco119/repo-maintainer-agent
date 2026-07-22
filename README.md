# Devin Remediator

Event-driven GitHub issue remediation using the Devin API, with a local dry-run mode.

```text
GitHub webhook / scanner / simulator
              │
              ▼
        SQLite ingest ──► priority FIFO ──► Devin sessions
              │                                  │
              └── JSON logs + OTel ◄── evaluator ◄─┘
                                      │
                              dashboard / MCP
```

Task lifecycle:

```text
QUEUED → WORKING → IN_REVIEW → EVALUATING
                         ├─→ MERGED
                         ├─→ AWAITING_HUMAN_REVIEW
                         └─→ FAILED
```

## Run

```bash
docker compose up --build
# or: pip install -e '.[dev]' && DRY_RUN=1 uvicorn app.main:app --reload
curl -X POST localhost:8000/simulate/issue -H 'content-type: application/json' \
  -d '{"title":"Fix test","body":"Please fix this","labels":["easy"]}'
```

The MCP stub is `python -m app.mcp_server`; it speaks JSON-RPC 2.0 over stdio and exposes
`list_tasks`, `get_task`, and `get_metrics`.

The optional Slack notifier posts human-style lifecycle updates for queued work, session
starts, blockers, pull requests, evaluations, and terminal failures. `GET /report` or
`POST /report` sends a compact daily-style summary to Slack and returns the same summary
as JSON. Without a webhook configured, notifications are emitted as structured fallback
logs so dry-run demos still show the teammate updates.

### Conversational Slack bot

For a private, no-public-URL Slack bot, use
[`slack-app-manifest.yml`](slack-app-manifest.yml) at
api.slack.com/apps → **Create New App → From a manifest**. After creating the app,
create an App-Level token with the `connections:write` scope, then configure:

| Variable | Default | Purpose |
|---|---|---|
| `SLACK_BOT_TOKEN` | empty | Slack bot token (`xoxb-...`) |
| `SLACK_APP_TOKEN` | empty | Socket Mode app token (`xapp-...`) |
| `SLACK_CHANNEL` | empty | Channel for proactive bot lifecycle posts |
| `SLACK_WEBHOOK_URL` | empty | Incoming Webhook fallback when bot channel is unset |
| `DASHBOARD_URL` | empty | Optional dashboard link included in Slack status/report replies |

The FastAPI lifespan starts Socket Mode only when both bot and app tokens are set.
The bot understands `status`, `report`, `issue #N`, `scan`, and
`remediate owner/repo#N` (or `remediate #N`). Connection and handler failures are isolated
from remediation workers and the API.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `DEVIN_API_KEY` | empty | Devin bearer token |
| `DEVIN_BASE_URL` | Devin v1 URL | API endpoint |
| `DRY_RUN` | `0` | Simulate Devin sessions |
| `GITHUB_TOKEN` | empty | GitHub REST access; absent means graceful skip |
| `DB_PATH` | `remediator.db` | SQLite location |
| `MAX_PARALLEL_SESSIONS` | `3` | Worker concurrency |
| `POLL_INTERVAL` | `30` | Devin polling seconds |
| `SCAN_INTERVAL_MIN` | `0` | Scanner interval; zero disables schedule |
| `MAX_ISSUES_PER_SCAN` | `3` | Maximum security issues created per scan |
| `HOURS_PER_ISSUE` | `4.0` | Planning estimate used for reclaimed-hours metric |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | empty | Optional OTLP HTTP endpoint |
| `SLACK_WEBHOOK_URL` | empty | Optional Slack Incoming Webhook URL |
| `AUTO_MERGE` | `0` | Set to `1` to allow squash auto-merge after passing checks |
| `GITHUB_POLL_INTERVAL_SEC` | `30` | Seconds between GitHub issue polls when `GITHUB_TOKEN` is set |

The scanner downloads the fork's `requirements/base.txt`, runs `pip-audit -r`, and falls
back to OSV API queries for up to 40 pinned dependencies when pip-audit is unavailable or
fails. It creates at most `MAX_ISSUES_PER_SCAN` security issues, de-duplicated by a marker
in the issue body. Without `GITHUB_TOKEN`, findings use deterministic synthetic issue numbers
and remain fully demoable locally.

Metrics include TTR median (ingest to completion), first-pass success, success split by
easy/medium/hard labels, average evaluation score, blocked/escalated count, human approval
rate, daily throughput normalized by elapsed days, and engineer hours reclaimed. Evaluator
checks the PR's existence and (when authenticated) its head commit check-runs. Pending checks
are temporarily treated as passing; missing credentials or API errors produce an unknown
check state and a conservative 0.5 score when the PR exists. Pending or missing checks
cannot qualify for auto-merge. Cost is intentionally not
estimated because Devin billing data is not available through this interface.

When `AUTO_MERGE=1`, the evaluator squash-merges only PRs with explicitly passing checks
and either a `security` issue label or a small diff (at most three changed files and
50 additions plus deletions). Other successful evaluations become
`AWAITING_HUMAN_REVIEW` with a rationale in the evaluation record and Slack update.
`MERGED` and `AWAITING_HUMAN_REVIEW` both count as remediated throughput.

### Issue-driven demo

With `GITHUB_TOKEN` configured, the background poller checks open issues every
`GITHUB_POLL_INTERVAL_SEC` seconds. To demo the complete flow, open an issue titled
**`dependency scan`** in the configured repository. The agent runs the scanner, comments
with the result summary, closes the trigger issue, and queues any findings. Other newly
opened issues are ingested and sent to Devin without a webhook or manual `curl`.
