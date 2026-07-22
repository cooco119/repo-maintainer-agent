import asyncio
import os
import uuid
import httpx
from .config import DEVIN_API_KEY, DEVIN_BASE_URL, DRY_RUN

class DevinClient:
    def __init__(self):
        self.sessions = {}

    async def _request(self, method, path, **kwargs):
        headers = {"Authorization": f"Bearer {DEVIN_API_KEY}"}
        async with httpx.AsyncClient(base_url=DEVIN_BASE_URL, timeout=30) as client:
            response = await client.request(method, path, headers=headers, **kwargs)
            response.raise_for_status()
            return response.json()

    async def create_session(self, prompt):
        if DRY_RUN or os.getenv("DRY_RUN") == "1":
            sid = f"dry-{uuid.uuid4().hex[:12]}"
            self.sessions[sid] = {"started": asyncio.get_running_loop().time(), "messages": []}
            return {"session_id": sid, "url": f"http://dry-run.local/session/{sid}"}
        return await self._request("POST", "/sessions", json={"prompt": prompt, "idempotent": True})

    async def get_session(self, session_id):
        if DRY_RUN or os.getenv("DRY_RUN") == "1":
            elapsed = asyncio.get_running_loop().time() - self.sessions[session_id]["started"]
            if elapsed < 0.05: status = "working"
            else: status = "finished"
            return {"status_enum": status, "structured_output": {}, "pull_request": {
                "url": "https://github.com/cooco119/superset/pull/999"} if status == "finished" else None}
        return await self._request("GET", f"/session/{session_id}")

    async def send_message(self, session_id, message):
        if DRY_RUN or os.getenv("DRY_RUN") == "1":
            self.sessions.setdefault(session_id, {"messages": []})["messages"].append(message)
            return {"ok": True}
        return await self._request("POST", f"/session/{session_id}/message", json={"message": message})
