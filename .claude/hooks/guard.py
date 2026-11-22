#!/usr/bin/env python3
"""
PreToolUse guard for the code-quality-fix skill.

Active only while a fix session is running (git_fix.py start-session writes
.claude/.ai-fix-active with the target repo path; end-session removes it).
While active:
  * Edit / Write / MultiEdit / NotebookEdit inside the target repo are allowed ONLY for
    .java files under src/main/java or src/test/java (checked on the resolved path).
  * Bash may not run git commands that change branches or history, or gh pr, directly:
    those must go through git_fix.py, which enforces ai-fix/* branches, approval and DRY_RUN.
Exit code 2 blocks the tool call; the message on stderr goes back to Claude.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
MARKER = PROJECT_DIR / ".claude" / ".ai-fix-active"
WRITABLE_PREFIXES = ("src/main/java/", "src/test/java/")
BLOCKED_BASH = re.compile(
    r"\b(git\s+(-C\s+\S+\s+)?(commit|push|merge|rebase|reset|checkout|switch|branch|clean|stash|tag|cherry-pick|am|apply)"
    r"|gh\s+pr|mvn\b.*\b(deploy|release:))")


def deny(msg: str) -> None:
    print(f"Blocked by code-quality-fix guard: {msg}", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    if not MARKER.exists():
        return
    repo = Path(MARKER.read_text(encoding="utf-8").strip()).resolve()
    event = json.load(sys.stdin)
    tool, inp = event.get("tool_name", ""), event.get("tool_input", {}) or {}

    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        raw = inp.get("file_path") or inp.get("notebook_path") or ""
        p = Path(raw)
        if not p.is_absolute():
            p = Path(event.get("cwd") or ".") / p
        p = p.resolve()
        if p == repo or repo in p.parents:
            rel = p.relative_to(repo).as_posix()
            if not (rel.startswith(WRITABLE_PREFIXES) and rel.endswith(".java")):
                deny(f"during a fix session only .java files under {WRITABLE_PREFIXES} may be written "
                     f"in {repo.name} (got {rel})")

    elif tool == "Bash":
        cmd = inp.get("command", "")
        if "git_fix.py" in cmd or "run_tests.py" in cmd or "list_findings.py" in cmd:
            if re.search(r"[;&|`]|\$\(", cmd):
                deny("run the skill scripts as a single command, without chaining other commands")
            return
        if BLOCKED_BASH.search(cmd):
            deny("git branch/history commands and `gh pr` must go through git_fix.py during a fix session")


if __name__ == "__main__":
    main()
