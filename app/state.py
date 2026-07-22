import json
from .db import connect, now
from .logging_utils import log_event
from .telemetry import span

STATES = ("QUEUED", "WORKING", "BLOCKED", "IN_REVIEW", "EVALUATING", "DONE", "FAILED")
ALLOWED_TRANSITIONS = {
    "QUEUED": {"WORKING", "FAILED"},
    "WORKING": {"BLOCKED", "IN_REVIEW", "FAILED"},
    "BLOCKED": {"WORKING", "FAILED"},
    "IN_REVIEW": {"EVALUATING", "FAILED"},
    "EVALUATING": {"DONE", "FAILED"},
    "DONE": set(),
    "FAILED": {"QUEUED"},
}

def transition(task_id: int, target: str, correlation_id: str, payload=None):
    with connect() as db:
        row = db.execute("SELECT state FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row or target not in ALLOWED_TRANSITIONS[row["state"]]:
            raise ValueError(f"invalid transition to {target}")
        db.execute("UPDATE tasks SET state=?,updated_at=? WHERE id=?", (target, now(), task_id))
        db.execute("INSERT INTO events(task_id,correlation_id,event_type,payload,created_at) VALUES(?,?,?,?,?)",
                   (task_id, correlation_id, f"STATE_{target}", json.dumps(payload or {}), now()))
    with span(f"task.transition.{target}", correlation_id):
        log_event("state_transition", correlation_id, task_id=task_id, state=target)
