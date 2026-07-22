import hashlib
import re
import httpx
from .config import GITHUB_TOKEN, REPO
from .ingest import ingest_issue

async def scan():
    url = "https://raw.githubusercontent.com/cooco119/superset/master/requirements/base.txt"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url)
    if not response.is_success:
        return []
    vulnerabilities = []
    for line in response.text.splitlines():
        match = re.match(r"^\s*([A-Za-z0-9_.-]+)==([^\s]+)", line)
        if match and "django" in match.group(1).lower():
            vulnerabilities.append((match.group(1), match.group(2), "upgrade dependency"))
    created = []
    for package, version, detail in vulnerabilities:
        key = hashlib.sha256(f"{REPO}#{package}#{version}".encode()).hexdigest()[:16]
        title = f"Security vulnerability in {package} {version}"
        body = f"Automated audit finding: {detail}.\n<!-- remediator-key:{key} -->"
        if GITHUB_TOKEN:
            async with httpx.AsyncClient(timeout=20, headers={"Authorization": f"Bearer {GITHUB_TOKEN}"} ) as client:
                await client.post(f"https://api.github.com/repos/{REPO}/issues",
                                  json={"title": title, "body": body, "labels": ["security"]})
        task, _ = ingest_issue(REPO, len(created) + 1, title, body, ["security"])
        created.append(task)
    return created
