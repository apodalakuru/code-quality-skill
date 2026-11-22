#!/usr/bin/env python3
"""
List open findings, most severe first, normalised to one shape:
  {id, source, rule, severity, file, line, message, rule_description}

  python3 list_findings.py --source file|sonar|codeql [--min-severity MAJOR] [--max 5] [--repo PATH]

Sources:
  file    findings.json at the repo root (demo)
  sonar   SonarQube API      (SONAR_URL, SONAR_PROJECT_KEY, SONAR_TOKEN)
  codeql  GitHub code scanning (GITHUB_REPO=owner/name, GITHUB_TOKEN)
Read-only. Only .java findings are returned.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from base64 import b64encode
from pathlib import Path

from common import fail, repo_root

SEVERITY_ORDER = ["INFO", "MINOR", "MAJOR", "CRITICAL", "BLOCKER"]
CODEQL_TO_SONAR = {"note": "MINOR", "warning": "MAJOR", "error": "CRITICAL",
                   "low": "MINOR", "medium": "MAJOR", "high": "CRITICAL", "critical": "BLOCKER"}


def _rank(sev: str) -> int:
    sev = (sev or "INFO").upper()
    return SEVERITY_ORDER.index(sev) if sev in SEVERITY_ORDER else 0


def _get_json(url: str, headers: dict) -> dict | list:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        fail(f"Environment variable {name} is required for this source")
    return value


def from_file(repo: Path) -> list[dict]:
    p = repo / "findings.json"
    if not p.exists():
        fail(f"No findings.json in {repo}")
    return json.loads(p.read_text(encoding="utf-8"))


def from_sonar() -> list[dict]:
    base, key, token = _env("SONAR_URL").rstrip("/"), _env("SONAR_PROJECT_KEY"), _env("SONAR_TOKEN")
    headers = {"Authorization": "Basic " + b64encode(f"{token}:".encode()).decode()}
    q = urllib.parse.urlencode({"componentKeys": key, "resolved": "false", "ps": 100,
                                "types": "BUG,VULNERABILITY,CODE_SMELL"})
    data = _get_json(f"{base}/api/issues/search?{q}", headers)
    rule_cache: dict[str, str] = {}
    out = []
    for i in data.get("issues", []):
        rule = i["rule"]
        if rule not in rule_cache:
            try:
                r = _get_json(f"{base}/api/rules/show?key={urllib.parse.quote(rule)}", headers)
                rule_cache[rule] = r.get("rule", {}).get("name", "")
            except Exception:
                rule_cache[rule] = ""
        out.append({
            "id": i["key"], "source": "sonar", "rule": rule, "severity": i.get("severity", "MAJOR"),
            "file": i["component"].split(":", 1)[-1], "line": i.get("line"),
            "message": i.get("message", ""), "rule_description": rule_cache[rule],
        })
    return out


def from_codeql() -> list[dict]:
    repo = _env("GITHUB_REPO")
    headers = {"Authorization": f"Bearer {_env('GITHUB_TOKEN')}", "Accept": "application/vnd.github+json"}
    alerts = _get_json(
        f"https://api.github.com/repos/{repo}/code-scanning/alerts?state=open&tool_name=CodeQL&per_page=100",
        headers)
    out = []
    for a in alerts:
        rule = a.get("rule", {})
        inst = a.get("most_recent_instance", {})
        loc = inst.get("location", {})
        sev = rule.get("security_severity_level") or rule.get("severity") or "warning"
        out.append({
            "id": str(a["number"]), "source": "codeql", "rule": rule.get("id", ""),
            "severity": CODEQL_TO_SONAR.get(sev, "MAJOR"), "file": loc.get("path", ""),
            "line": loc.get("start_line"), "message": inst.get("message", {}).get("text", ""),
            "rule_description": rule.get("description", ""),
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=os.environ.get("FINDINGS_SOURCE", "file"),
                    choices=["file", "sonar", "codeql"])
    ap.add_argument("--min-severity", default=os.environ.get("MIN_SEVERITY", "MAJOR"),
                    type=str.upper, choices=SEVERITY_ORDER)
    ap.add_argument("--max", type=int, default=int(os.environ.get("MAX_FINDINGS", "5")))
    ap.add_argument("--repo")
    args = ap.parse_args()

    repo = repo_root(args.repo)
    loaders = {"file": lambda: from_file(repo), "sonar": from_sonar, "codeql": from_codeql}
    try:
        raw = loaders[args.source]()
    except Exception as e:  # network / auth / JSON errors
        fail(f"Could not load findings from {args.source}: {e}")
    findings = [f for f in raw
                if f.get("file", "").endswith(".java") and _rank(f["severity"]) >= _rank(args.min_severity)]
    findings.sort(key=lambda f: _rank(f["severity"]), reverse=True)
    print(json.dumps(findings[: args.max], indent=2))


if __name__ == "__main__":
    main()
