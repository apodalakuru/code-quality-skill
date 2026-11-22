"""
Shared helpers for the code-quality-fix skill scripts.

The scripts are the ONLY place where the skill runs git, Maven or network calls.
Each one keeps the guardrails the original MCP server had:
  * file access is confined to the target repo
  * the only build command is `mvn -B -q test`
  * git only works on ai-fix/* branches; push / PR are skipped when DRY_RUN=true

Session state (base branch, attempts, results) lives in <repo>/.git/ai-fix/state.json,
so it never shows up in a diff or a commit.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[4]          # .../code-quality-skill
ACTIVE_MARKER = PROJECT_DIR / ".claude" / ".ai-fix-active"  # read by the guard hook

BRANCH_PATTERN = re.compile(r"^ai-fix/[A-Za-z0-9._\-/]{1,80}$")
WRITABLE_PREFIXES = ("src/main/java/", "src/test/java/")
MAX_FILE_BYTES = 200_000

DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "3"))
MAVEN_CMD = os.environ.get("MAVEN_CMD", "mvn")
BUILD_TIMEOUT_SEC = int(os.environ.get("BUILD_TIMEOUT_SEC", "900"))


def repo_root(arg: str | None = None) -> Path:
    """--repo argument, else REPO_ROOT, else the demo working copy. Relative paths resolve from the project dir."""
    raw = arg or os.environ.get("REPO_ROOT") or ".work/demo-java-app"
    p = Path(raw)
    if not p.is_absolute():
        p = PROJECT_DIR / p
    p = p.resolve()
    if not (p / ".git").exists():
        fail(f"{p} is not a git repository (run setup_demo.sh for the demo app)")
    return p


def fail(msg: str, code: int = 1) -> None:
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(code)


def ok(**data) -> None:
    print(json.dumps({"ok": True, **data}, indent=2))


def run(args: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    # shell=False and a fixed argument list: Claude never builds a command string
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def git(repo: Path, *args: str) -> str:
    r = run(["git", *args], repo)
    if r.returncode != 0:
        fail(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def is_writable(repo: Path, path: str) -> bool:
    """True only for .java files under src/main/java or src/test/java, checked on the RESOLVED path."""
    p = (repo / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if repo not in p.parents:
        return False
    norm = p.relative_to(repo).as_posix()
    return norm.startswith(WRITABLE_PREFIXES) and norm.endswith(".java")


# ------------------------------------------------------------------ session state
def state_path(repo: Path) -> Path:
    return repo / ".git" / "ai-fix" / "state.json"


def load_state(repo: Path) -> dict:
    p = state_path(repo)
    if not p.exists():
        fail("No active session. Run: git_fix.py start-session")
    return json.loads(p.read_text(encoding="utf-8"))


def save_state(repo: Path, state: dict) -> None:
    p = state_path(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")
