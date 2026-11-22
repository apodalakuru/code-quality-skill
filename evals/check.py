#!/usr/bin/env python3
"""
Score a dry run of the skill on the demo app.

After `/code-quality-fix file 3` with every fix approved (DRY_RUN=true), each fix is a commit on
a local ai-fix/* branch. This script checks each branch against evals/expected.json.

  python3 evals/check.py [--repo .work/demo-java-app]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")[:40]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(ROOT / ".work" / "demo-java-app"))
    repo = Path(ap.parse_args().repo).resolve()
    cases = json.loads((ROOT / "evals" / "expected.json").read_text())
    passed = 0
    for c in cases:
        branch = f"ai-fix/{slug(c['rule'])}-{slug(c['finding_id'])}"
        problems = []
        src = git(repo, "show", f"{branch}:{c['file']}")
        if src.returncode != 0:
            problems.append(f"branch {branch} or file missing")
        else:
            for s in c["expect"].get("source_must_contain", []):
                if s not in src.stdout:
                    problems.append(f"missing '{s}'")
            for s in c["expect"].get("source_must_not_contain", []):
                if s in src.stdout:
                    problems.append(f"still contains '{s}'")
            test = c["expect"].get("new_test")
            if test and git(repo, "show", f"{branch}:{test}").returncode != 0:
                problems.append(f"no test file {test}")
        ok = not problems
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {c['rule']:<20} {branch}  {'; '.join(problems)}")
    print(f"\n{passed}/{len(cases)} findings fixed as expected")


if __name__ == "__main__":
    main()
