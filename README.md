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

## Run

```bash
docker compose up --build
# or: pip install -e '.[dev]' && DRY_RUN=1 uvicorn app.main:app --reload
curl -X POST localhost:8000/simulate/issue -H 'content-type: application/json' \
  -d '{"title":"Fix test","body":"Please fix this","labels":["easy"]}'
```

The MCP stub is `python -m app.mcp_server`; it speaks JSON-RPC 2.0 over stdio and exposes
`list_tasks`, `get_task`, and `get_metrics`.

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
| `OTEL_EXPORTER_OTLP_ENDPOINT` | empty | Optional OTLP HTTP endpoint |

Metrics include TTR median (ingest to completion), first-pass success, success split by
easy/medium/hard labels, and daily throughput. Cost is intentionally not estimated because
Devin billing data is not available through this interface.
