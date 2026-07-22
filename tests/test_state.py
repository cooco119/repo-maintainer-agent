import os
os.environ["DB_PATH"] = "/tmp/devin-remediator-state-test.db"
from app.db import init_db, connect
from app.ingest import ingest_issue
from app.state import transition

def setup_function():
    init_db()
    with connect() as db:
        db.executescript("DELETE FROM evals; DELETE FROM reviews; DELETE FROM events; DELETE FROM tasks;")

def test_valid_and_invalid_transition():
    task, _ = ingest_issue("x/y", 1, "title", "body")
    transition(task["id"], "WORKING", task["correlation_id"])
    assert True
    try:
        transition(task["id"], "DONE", task["correlation_id"])
    except ValueError:
        pass
    else:
        raise AssertionError("invalid transition accepted")

def test_idempotent_ingest():
    first, created = ingest_issue("x/y", 2, "title", "Same body")
    second, duplicate = ingest_issue("x/y", 2, "other", " same   body ")
    assert created and not duplicate and first["id"] == second["id"]
