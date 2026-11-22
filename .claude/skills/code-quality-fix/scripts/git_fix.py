#!/usr/bin/env python3
"""
Guarded git operations for the code-quality-fix skill.

  git_fix.py start-session [--base main]           clean tree required; activates the write guard
  git_fix.py start-branch --rule R --id I --file F  fresh ai-fix/<rule>-<id> from base (counts attempts)
  git_fix.py diff                                   diff for review + approval code
  git_fix.py discard                                throw away the attempt, back to base (before a retry)
  git_fix.py ship --approve CODE --title T --body B commit (+ push + PR unless DRY_RUN), only if CODE
                                                    matches the diff the user reviewed
  git_fix.py finish --status rejected|failed --detail D   discard and record the outcome
  git_fix.py summary                                results so far
  git_fix.py end-session                            back to base, deactivate the write guard

All commands accept --repo PATH (default: REPO_ROOT, else .work/demo-java-app).
Every refusal prints {"ok": false, "error": ...} and exits non-zero.
"""
from __future__ import annotations

import argparse
import hashlib
import re

from common import (ACTIVE_MARKER, BRANCH_PATTERN, DRY_RUN, MAX_ATTEMPTS, fail, git, is_writable,
                    load_state, ok, repo_root, run, save_state, state_path)


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")[:40]


def _changed_paths(repo) -> list[str]:
    # -z: NUL-separated, no quoting, no stripping of the leading status column
    r = run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], repo)
    if r.returncode != 0:
        fail(f"git status failed: {r.stderr.strip()}")
    entries, paths = r.stdout.split("\0"), []
    i = 0
    while i < len(entries):
        e = entries[i]
        if len(e) > 3:
            paths.append(e[3:])
            if e[0] in "RC":  # rename/copy: the next entry is the original path
                paths.append(entries[i + 1]); i += 1
        i += 1
    return paths


def _disallowed(repo) -> list[str]:
    return [p for p in _changed_paths(repo) if not is_writable(repo, p)]


def _diff(repo) -> str:
    git(repo, "add", "-N", "--", "src")  # intent-to-add so new test files appear in the diff
    return git(repo, "diff", "--", "src")


def _code(diff: str) -> str:
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()[:12]


def _current_branch(repo) -> str:
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD")


def _back_to_base(repo, base: str) -> None:
    git(repo, "reset", "--hard")
    git(repo, "clean", "-fd", "--", "src")
    git(repo, "checkout", base)


def _record(state: dict, status: str, detail: str) -> None:
    cur = state.get("current") or {}
    state["results"].append({"finding_id": cur.get("id"), "rule": cur.get("rule"), "file": cur.get("file"),
                             "branch": cur.get("branch"), "attempts": state["attempts"].get(cur.get("branch"), 0),
                             "status": status, "detail": detail})
    state["current"] = None


# ------------------------------------------------------------------ commands
def start_session(repo, a) -> None:
    if _changed_paths(repo):
        fail("Working tree is not clean; commit or stash your changes first")
    git(repo, "rev-parse", "--verify", a.base)
    git(repo, "checkout", a.base)
    save_state(repo, {"base": a.base, "attempts": {}, "results": [], "current": None})
    ACTIVE_MARKER.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_MARKER.write_text(str(repo), encoding="utf-8")
    ok(repo=str(repo), base=a.base, dry_run=DRY_RUN, max_attempts=MAX_ATTEMPTS)


def start_branch(repo, a) -> None:
    state = load_state(repo)
    branch = f"ai-fix/{_slug(a.rule)}-{_slug(a.id)}"
    if not BRANCH_PATTERN.match(branch):
        fail(f"Invalid branch name: {branch}")
    attempt = state["attempts"].get(branch, 0) + 1
    if attempt > MAX_ATTEMPTS:
        fail(f"Retry limit reached ({MAX_ATTEMPTS} attempts) for {branch}; run: finish --status failed")
    if _changed_paths(repo):
        fail("Working tree is not clean; run `discard` before starting a new attempt")
    git(repo, "checkout", state["base"])
    git(repo, "checkout", "-B", branch)
    state["attempts"][branch] = attempt
    state["current"] = {"id": a.id, "rule": a.rule, "file": a.file, "branch": branch}
    save_state(repo, state)
    ok(branch=branch, attempt=attempt, attempts_left=MAX_ATTEMPTS - attempt)


def diff(repo, a) -> None:
    load_state(repo)
    d = _diff(repo)
    ok(branch=_current_branch(repo), approval_code=_code(d), changed_files=_changed_paths(repo),
       disallowed_changes=_disallowed(repo), diff=d or "(empty diff)")


def discard(repo, a) -> None:
    state = load_state(repo)
    _back_to_base(repo, state["base"])
    ok(message=f"discarded changes, back on {state['base']}")


def ship(repo, a) -> None:
    state = load_state(repo)
    cur = state.get("current") or {}
    branch = _current_branch(repo)
    if not BRANCH_PATTERN.match(branch) or branch != cur.get("branch"):
        fail(f"Refusing to commit: on {branch}, expected the current ai-fix branch {cur.get('branch')}")
    if bad := _disallowed(repo):
        fail(f"Refusing to commit: changes outside src/{{main,test}}/java/**/*.java: {bad}")
    d = _diff(repo)
    if not d:
        fail("Nothing to commit")
    if a.approve != _code(d):
        fail("Approval code does not match the current diff. Show the diff to the user again and ask for approval.")

    git(repo, "add", "-A", "--", "src")
    git(repo, "commit", "-m", a.title, "-m", a.body)
    sha = git(repo, "rev-parse", "--short", "HEAD")
    if DRY_RUN:
        detail = f"DRY_RUN: committed {sha} on {branch} locally; not pushed, no PR"
    else:
        git(repo, "push", "-u", "origin", branch)
        r = run(["gh", "pr", "create", "--title", a.title, "--body", a.body, "--head", branch,
                 "--base", state["base"], "--label", "ai-generated"], repo)
        if r.returncode != 0:
            fail(f"Pushed {branch}, but gh pr create failed: {r.stderr.strip()}")
        detail = r.stdout.strip()
    _record(state, "pr_opened" if not DRY_RUN else "committed", detail)
    git(repo, "checkout", state["base"])
    save_state(repo, state)
    ok(commit=sha, branch=branch, detail=detail)


def finish(repo, a) -> None:
    state = load_state(repo)
    _back_to_base(repo, state["base"])
    _record(state, a.status, a.detail)
    save_state(repo, state)
    ok(status=a.status, detail=a.detail)


def summary(repo, a) -> None:
    state = load_state(repo)
    ok(dry_run=DRY_RUN, results=state["results"])


def end_session(repo, a) -> None:
    results = []
    if state_path(repo).exists():
        state = load_state(repo)
        results = state["results"]
        if not _changed_paths(repo):
            git(repo, "checkout", state["base"])
        state_path(repo).unlink()
    ACTIVE_MARKER.unlink(missing_ok=True)
    ok(message="session ended; write guard off", results=results)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start-session"); s.add_argument("--base", default="main")
    s = sub.add_parser("start-branch")
    s.add_argument("--rule", required=True); s.add_argument("--id", required=True); s.add_argument("--file", required=True)
    sub.add_parser("diff")
    sub.add_parser("discard")
    s = sub.add_parser("ship")
    s.add_argument("--approve", required=True); s.add_argument("--title", required=True); s.add_argument("--body", required=True)
    s = sub.add_parser("finish")
    s.add_argument("--status", required=True, choices=["rejected", "failed", "skipped"]); s.add_argument("--detail", default="")
    sub.add_parser("summary")
    sub.add_parser("end-session")

    a = ap.parse_args()
    repo = repo_root(a.repo)
    {"start-session": start_session, "start-branch": start_branch, "diff": diff, "discard": discard,
     "ship": ship, "finish": finish, "summary": summary, "end-session": end_session}[a.cmd](repo, a)


if __name__ == "__main__":
    main()
