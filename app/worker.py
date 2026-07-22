import asyncio
from .config import MAX_PARALLEL_SESSIONS, POLL_INTERVAL
from .db import connect, now
from .devin_client import DevinClient
from .logging_utils import log_event
from .notifier import notify
from .state import transition

class PriorityQueue:
    def __init__(self):
        self.queue = asyncio.PriorityQueue()
    async def put(self, task):
        priority = 0 if "security" in [x.lower() for x in task["labels"]] else 1
        await self.queue.put((priority, task["id"], task))
    async def get(self): return (await self.queue.get())[2]

class WorkerPool:
    def __init__(self):
        self.queue = PriorityQueue()
        self.client = DevinClient()
        self.semaphore = asyncio.Semaphore(MAX_PARALLEL_SESSIONS)
        self.tasks = set()

    async def enqueue(self, task):
        await self.queue.put(task)

    async def run_one(self, task):
        async with self.semaphore:
            cid = task["correlation_id"]
            try:
                transition(task["id"], "WORKING", cid)
                prompt = f"""Remediate GitHub issue #{task['issue_number']}: {task['title']}
Body: {task['body']}
Repository: {task['repo']}.
Fixes #{task['issue_number']}. Create branch remediator/issue-{task['issue_number']},
make the minimal safe fix, run relevant lint and tests, and open a pull request
against {task['repo']}'s master branch."""
                result = await self.client.create_session(prompt)
                await notify(
                    f"🔧 Starting work on issue #{task['issue_number']} — session: "
                    f"{result.get('url', 'pending')}",
                    cid,
                )
                with connect() as db:
                    db.execute("UPDATE tasks SET session_id=?,session_url=?,attempts=attempts+1,updated_at=? WHERE id=?",
                               (result["session_id"], result.get("url"), now(), task["id"]))
                while True:
                    status = await self.client.get_session(result["session_id"])
                    value = str(status.get("status_enum", "")).lower()
                    if value in {"blocked", "blocked_by_user"}:
                        transition(task["id"], "BLOCKED", cid)
                        if not task.get("blocked_escalated"):
                            await notify(
                                f"⚠️ I'm blocked on issue #{task['issue_number']}, "
                                "trying to unblock myself…",
                                cid,
                            )
                            await self.client.send_message(result["session_id"],
                                "Please continue using the available context and report concrete blockers.")
                            with connect() as db:
                                db.execute("UPDATE tasks SET blocked_escalated=1 WHERE id=?", (task["id"],))
                            task["blocked_escalated"] = 1
                            transition(task["id"], "WORKING", cid)
                        else:
                            await notify(f"🙋 Need human help on issue #{task['issue_number']}", cid)
                            raise RuntimeError("Devin session blocked")
                    elif value in {"finished", "completed", "done"}:
                        pr = status.get("pull_request") or {}
                        if not pr: raise RuntimeError("session finished without pull request")
                        with connect() as db:
                            db.execute("UPDATE tasks SET pr_url=?,updated_at=? WHERE id=?",
                                       (pr.get("url") or pr.get("html_url"), now(), task["id"]))
                        await notify(
                            f"✅ Opened PR for issue #{task['issue_number']}: "
                            f"{pr.get('url') or pr.get('html_url')} — please review.",
                            cid,
                        )
                        transition(task["id"], "IN_REVIEW", cid)
                        transition(task["id"], "EVALUATING", cid)
                        from .evaluator import evaluate_task
                        await evaluate_task(task["id"])
                        break
                    elif value in {"failed", "error"}:
                        raise RuntimeError("Devin session failed")
                    await asyncio.sleep(POLL_INTERVAL)
            except Exception as exc:
                log_event("task_failed", cid, task_id=task["id"], error=str(exc))
                with connect() as db:
                    attempts = db.execute("SELECT attempts FROM tasks WHERE id=?", (task["id"],)).fetchone()["attempts"]
                if attempts < 3:
                    try: transition(task["id"], "FAILED", cid); transition(task["id"], "QUEUED", cid)
                    except ValueError: pass
                    await self.enqueue(task)
                else:
                    try: transition(task["id"], "FAILED", cid)
                    except ValueError: pass
                    await notify(
                        f"❌ Issue #{task['issue_number']} failed after {attempts} attempts.",
                        cid,
                    )

    async def serve(self):
        while True:
            task = await self.queue.get()
            work = asyncio.create_task(self.run_one(task))
            self.tasks.add(work)
            work.add_done_callback(self.tasks.discard)
