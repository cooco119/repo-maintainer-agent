import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

import httpx

from .config import MAX_ISSUES_PER_SCAN, REPO
from .ingest import ingest_issue
from .gh_token import get_github_token, invalidate


def _pinned(text):
    return [
        (match.group(1), match.group(2))
        for line in text.splitlines()
        if (match := re.match(r"^\s*([A-Za-z0-9_.-]+)==([^\s;]+)", line))
    ][:40]


def _pip_audit(requirements):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "requirements.txt"
        path.write_text(requirements)
        try:
            result = subprocess.run(
                ["pip-audit", "-r", str(path), "-f", "json"],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError):
            pass
    return None


async def _osv_findings(packages):
    findings = []
    async with httpx.AsyncClient(timeout=20) as client:
        for package, version in packages:
            response = await client.post(
                "https://api.osv.dev/v1/query",
                json={"package": {"name": package, "ecosystem": "PyPI"}, "version": version},
            )
            if response.is_success:
                for vuln in response.json().get("vulns", []):
                    findings.append((package, version, vuln.get("id", "OSV finding")))
    return findings


async def scan():
    requirements_url = "https://raw.githubusercontent.com/cooco119/superset/master/requirements/base.txt"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(requirements_url)
    if not response.is_success:
        return []
    packages = _pinned(response.text)
    audit = _pip_audit(response.text)
    if audit is not None:
        vulnerabilities = [
            (item.get("name", "dependency"), item.get("version", "unknown"),
             ", ".join(v.get("id", "finding") for v in item.get("vulns", [])))
            for item in audit
        ]
    else:
        vulnerabilities = await _osv_findings(packages)
    created = []
    for package, version, detail in vulnerabilities[:MAX_ISSUES_PER_SCAN]:
        key = hashlib.sha256(f"{REPO}#{package}#{version}#{detail}".encode()).hexdigest()
        marker = f"<!-- remediator-key:{key} -->"
        title = f"Security vulnerability in {package} {version}"
        body = f"Automated pip-audit/OSV finding: {detail}.\n{marker}"
        issue_number = -int(key[:12], 16)
        token = get_github_token()
        if token:
            headers = {"Authorization": f"Bearer {token}"}
            async with httpx.AsyncClient(timeout=20, headers=headers) as client:
                existing = await client.get(
                    f"https://api.github.com/repos/{REPO}/issues",
                    params={"state": "open", "per_page": 100},
                )
                if existing.status_code == 401:
                    invalidate()
                if existing.is_success and any(marker in (i.get("body") or "") for i in existing.json()):
                    continue
                created_issue = await client.post(
                    f"https://api.github.com/repos/{REPO}/issues",
                    json={"title": title, "body": body, "labels": ["security"]},
                )
                if created_issue.status_code == 401:
                    invalidate()
                if created_issue.is_success:
                    issue_number = created_issue.json()["number"]
        task, is_new = ingest_issue(REPO, issue_number, title, body, ["security"])
        if is_new:
            created.append(task)
    return created
