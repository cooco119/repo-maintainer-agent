import json
import sys
from .db import init_db, connect
from .evaluator import metrics

def call(name, args):
    if name == "get_metrics": return metrics()
    with connect() as db:
        if name == "list_tasks":
            return [dict(r) for r in db.execute("SELECT id,repo,issue_number,title,state,pr_url FROM tasks ORDER BY id DESC")]
        if name == "get_task":
            row = db.execute("SELECT * FROM tasks WHERE id=?", (args.get("task_id"),)).fetchone()
            return dict(row) if row else None
    return None

def main():
    init_db()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            method, params = request.get("method"), request.get("params", {})
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "devin-remediator", "version": "0.1"}}
            elif method == "tools/list":
                result = {"tools": [{"name": n, "description": n, "inputSchema": {"type": "object"}}
                                    for n in ("list_tasks", "get_task", "get_metrics")]}
            elif method == "tools/call":
                result = {"content": [{"type": "text", "text": json.dumps(call(params.get("name"), params.get("arguments", {})))}]}
            else: result = {}
            print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}), flush=True)
        except Exception as exc:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(exc)}}), flush=True)
if __name__ == "__main__": main()
