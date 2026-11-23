#!/usr/bin/env python3
"""
Pre-tool guard for the code-quality-fix plugin (Claude Code, GitHub Copilot CLI, Cursor).

Active only while a fix session is running: `git_fix.py start-session` writes a marker to
~/.code-quality-fix/active/ (or $CODE_QUALITY_FIX_HOME/active/) and `end-session` removes it.
While a session is active for a repo:
  * file-writing tools may touch that repo ONLY for .java files under src/main/java or
    src/test/java (checked on the resolved path, so ../ cannot get around it);
  * shell commands run from the project or the repo may not run git commands that change
    branches or history, or `gh pr`, directly: those go through git_fix.py, which enforces
    ai-fix/* branches, the approval code and DRY_RUN.

Accepted payloads (JSON on stdin):
  Claude Code / Copilot (PascalCase hooks) / Cursor preToolUse:  {tool_name, tool_input, cwd}
  Copilot (camelCase hooks):                                     {toolName, toolArgs, cwd}
  Cursor beforeShellExecution:                                   {command, cwd}
A block is exit code 2 with the reason on stderr, which all three tools treat as "deny".
A JSON decision is also printed on stdout for tools that read one.
Anything this guard cannot parse is allowed: the scripts re-check every path before committing.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

STATE_HOME = Path(os.environ.get("CODE_QUALITY_FIX_HOME") or Path.home() / ".code-quality-fix")
ACTIVE_DIR = STATE_HOME / "active"
WRITABLE_PREFIXES = ("src/main/java/", "src/test/java/")
SKILL_SCRIPTS = ("git_fix.py", "run_tests.py", "list_findings.py")
BLOCKED_SHELL = re.compile(
    r"\b(git\s+(-C\s+\S+\s+)?(commit|push|merge|rebase|reset|checkout|switch|branch|clean|stash|tag|cherry-pick|am|apply)"
    r"|gh\s+pr|mvn\b.*\b(deploy|release:))")
SHELL_TOOL = re.compile(r"^(bash|shell|powershell|terminal|run_terminal_cmd|run_in_terminal|run_shell_command)$", re.I)
WRITE_TOOL = re.compile(r"edit|write|create|delete|replace|patch|notebook", re.I)
PATH_KEYS = ("file_path", "notebook_path", "path", "filePath", "target_file", "file")
PATCH_PATH = re.compile(r"^(?:\*\*\* (?:Add|Update|Delete) File: |\+\+\+ b/|--- a/)(.+)$", re.M)


def deny(msg: str) -> None:
    reason = f"Blocked by code-quality-fix guard: {msg}"
    print(json.dumps({"permission": "deny", "agent_message": reason, "user_message": reason,
                      "permissionDecision": "deny", "permissionDecisionReason": reason}))
    print(reason, file=sys.stderr)
    sys.exit(2)


def active_sessions() -> list[dict]:
    sessions = []
    for f in ACTIVE_DIR.glob("*.json") if ACTIVE_DIR.is_dir() else []:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            sessions.append({"repo": Path(d["repo"]).resolve(), "project": Path(d["project"]).resolve()})
        except (OSError, ValueError, KeyError):
            continue
    return sessions


def inside(p: Path, root: Path) -> bool:
    return p == root or root in p.parents


def parse(event: dict) -> tuple[str, dict, Path]:
    tool = event.get("tool_name") or event.get("toolName") or ""
    args = event.get("tool_input") or event.get("toolArgs") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {"command": args} if SHELL_TOOL.match(tool) else {}
    if not tool and "command" in event:  # Cursor beforeShellExecution
        tool, args = "shell", {"command": event["command"]}
    roots = event.get("workspace_roots") or []
    cwd = (event.get("cwd") or (roots[0] if roots else None) or os.environ.get("CLAUDE_PROJECT_DIR")
           or os.environ.get("CURSOR_PROJECT_DIR") or os.getcwd())
    return tool, (args if isinstance(args, dict) else {}), Path(cwd).resolve()


def target_paths(args: dict, cwd: Path) -> list[Path]:
    raw = [args[k] for k in PATH_KEYS if isinstance(args.get(k), str) and args[k]]
    for k in ("patch", "input", "diff"):
        if isinstance(args.get(k), str):
            raw += [m.strip() for m in PATCH_PATH.findall(args[k]) if m.strip() != "/dev/null"]
    out = []
    for r in raw:
        p = Path(r).expanduser()
        out.append((p if p.is_absolute() else cwd / p).resolve())
    return out


def check_write(args: dict, cwd: Path, sessions: list[dict]) -> None:
    for p in target_paths(args, cwd):
        for s in sessions:
            repo = s["repo"]
            if inside(p, repo):
                rel = p.relative_to(repo).as_posix()
                if not (rel.startswith(WRITABLE_PREFIXES) and rel.endswith(".java")):
                    deny(f"during a fix session only .java files under {WRITABLE_PREFIXES} may be written "
                         f"in {repo.name} (got {rel})")


def check_shell(cmd: str, cwd: Path, sessions: list[dict]) -> None:
    if any(name in cmd for name in SKILL_SCRIPTS):
        if re.search(r"[;&|`]|\$\(", cmd):
            deny("run the skill scripts as a single command, without chaining other commands")
        return
    relevant = any(inside(cwd, s["project"]) or inside(cwd, s["repo"]) or str(s["repo"]) in cmd
                   for s in sessions)
    if relevant and BLOCKED_SHELL.search(cmd):
        deny("git branch/history commands and `gh pr` must go through git_fix.py during a fix session")


def main() -> None:
    sessions = active_sessions()
    if not sessions:
        return
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return
    tool, args, cwd = parse(event)
    if SHELL_TOOL.match(tool) or (not WRITE_TOOL.search(tool) and isinstance(args.get("command"), str)):
        check_shell(str(args.get("command", "")), cwd, sessions)
    elif WRITE_TOOL.search(tool):
        check_write(args, cwd, sessions)


if __name__ == "__main__":
    main()
