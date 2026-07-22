import hashlib
import json
import uuid
from .db import connect, now, row_task
from .logging_utils import log_event

def key_for(repo, issue_number, body):
    normalized = " ".join((body or "").split()).strip().lower()
    return hashlib.sha256(f"{repo}#{issue_number}#{normalized}".encode()).hexdigest()

def ingest_issue(repo, issue_number, title, body, labels=None):
    labels = labels or []
    key = key_for(repo, issue_number, body)
    correlation_id = str(uuid.uuid4())
    with connect() as db:
        existing = db.execute("SELECT * FROM tasks WHERE idempotency_key=?", (key,)).fetchone()
        if existing:
            log_event("duplicate_ingest", existing["correlation_id"], task_id=existing["id"])
            return row_task(existing), False
        timestamp = now()
        cursor = db.execute("""INSERT INTO tasks(correlation_id,repo,issue_number,title,body,labels,state,
          idempotency_key,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
          (correlation_id, repo, issue_number, title, body or "", json.dumps(labels), "QUEUED",
           key, timestamp, timestamp))
        task_id = cursor.lastrowid
        db.execute("INSERT INTO events(task_id,correlation_id,event_type,payload,created_at) VALUES(?,?,?,?,?)",
                   (task_id, correlation_id, "INGESTED", json.dumps({"title": title}), timestamp))
        task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    log_event("issue_ingested", correlation_id, task_id=task_id)
    return row_task(task), True
