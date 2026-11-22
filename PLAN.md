# Plan: convert `code-quality-agent` into a Claude Code skill

## 1. The core idea

The current project is a **LangGraph program that calls Claude through the API**. A skill turns
this around: **Claude Code is the orchestrator and the model**, and the skill gives it the
procedure, the rules, and a set of guarded scripts.

| Today (agent) | As a skill |
|---|---|
| `agent/graph.py`: fixed LangGraph workflow | `SKILL.md`: numbered step-by-step procedure Claude follows |
| `ChatAnthropic` + `FixProposal` structured output | Claude Code itself reads the code and edits files |
| `agent/prompts.py` `SYSTEM_PROMPT` rules | `references/fix-rules.md` (loaded by SKILL.md) |
| `RETRY_BLOCK` (build error fed back) | Step "build failed → read output, correct, retry ≤ 3" |
| `interrupt()` + `MemorySaver` | Show the diff, then `AskUserQuestion` approve / reject |
| `mcp_server/server.py` tools + guardrails | `scripts/*.py` CLIs that keep the same checks, plus a hook |
| `mcp_server/sources.py` | `scripts/list_findings.py` (reused almost unchanged) |
| `agent/config.py` env settings | Same env vars, read by the scripts; defaults stated in SKILL.md |
| `agent/run.py` CLI | Not needed: user types `/code-quality-fix` |

Dropped dependencies: `langgraph`, `langchain-anthropic`, `langchain-mcp-adapters`, and the
`ANTHROPIC_API_KEY` requirement. The scripts need only the Python standard library.

## 2. Target layout

```
code-quality-skill/
├── .claude/
│   ├── skills/code-quality-fix/
│   │   ├── SKILL.md                  # frontmatter + the procedure
│   │   ├── references/
│   │   │   ├── fix-rules.md          # from SYSTEM_PROMPT (smallest change, JUnit 5, no PHI, no new deps)
│   │   │   ├── pr-template.md        # from commit_and_pr() body
│   │   │   └── rule-playbooks.md     # known fixes: java/sql-injection, java:S2245, java:S108, ...
│   │   └── scripts/
│   │       ├── list_findings.py      # file | sonar | codeql -> normalised JSON, severity filter, sorted
│   │       ├── run_tests.py          # fixed `mvn -B -q test`, timeout, JSON {passed, exit_code, output_tail}
│   │       └── git_fix.py            # start-branch | diff | discard | commit | open-pr, with ai-fix/* + DRY_RUN checks
│   ├── hooks/guard_writes.py         # PreToolUse: block Edit/Write outside src/{main,test}/java/**/*.java
│   └── settings.json                 # registers the hook + allowlists the skill's scripts
├── demo-java-app/                    # copied from the agent project (3 seeded findings)
├── evals/                            # expected outcome per seeded finding
├── setup_demo.sh                     # no venv needed any more; just git-init the demo app
└── README.md
```

Optional later: package as a **plugin** (`.claude-plugin/plugin.json` + `skills/` + `hooks/`) so
other repos can install it with one command instead of copying `.claude/`.

## 3. SKILL.md outline

Frontmatter:

```yaml
---
name: code-quality-fix
description: Fix SonarQube / CodeQL findings in a Java Maven project - one finding at a time,
  with a JUnit test, a passing Maven build, and human approval before any commit or PR.
  Use when the user asks to fix, remediate or clear Sonar/CodeQL/static-analysis findings.
argument-hint: "[file|sonar|codeql] [max-findings]"
allowed-tools: Read, Edit, Write, Bash(python3 *scripts/*), AskUserQuestion
---
```

Body (the graph, written as steps):

1. **Fetch** - `python3 scripts/list_findings.py --source $SOURCE --min-severity MAJOR --max 5`.
   Print the list. Stop if empty.
2. **For each finding, in order:**
   1. `git_fix.py start-branch ai-fix/<rule>-<id>` (refuses a dirty tree).
   2. Read the source file and its test (`src/test/java/...Test.java`), plus `rule-playbooks.md`
      if the rule is listed.
   3. Apply the fix following `fix-rules.md`; add/extend a JUnit 5 test.
   4. `run_tests.py`. If it fails: read the tail, `git_fix.py discard` + `start-branch`, correct,
      retry. **Max 3 attempts**, then discard and record `failed`.
   5. On a green build: `git_fix.py diff`, show the finding, explanation, test summary, risk
      (low/medium/high) and the diff, then **ask with AskUserQuestion**: Approve / Reject (+ comment).
      Never commit without an explicit "Approve" in this step.
   6. Approved → `git_fix.py commit` then `git_fix.py open-pr` using `pr-template.md`.
      Rejected → `git_fix.py discard`, record `rejected` with the reason.
3. **Summarize** - table of status / rule / file / detail (PR URL, reason or failure).

## 4. Keeping the guardrails (most important part)

In the agent, safety came from code: the LLM could only *propose*, and `interrupt()` made approval
mandatory. In a skill, Claude has real tools, so instructions alone are not enough. Keep the
safety in code:

| Guardrail | How it is enforced in the skill |
|---|---|
| Write only `.java` under `src/main/java`, `src/test/java` | `PreToolUse` hook on `Edit`/`Write` checks the resolved path and denies otherwise |
| Only `mvn -B -q test` runs | `run_tests.py` has a fixed argv; `allowed-tools` restricts Bash to the scripts |
| Branches only `ai-fix/*`; no commit on base | `git_fix.py` keeps `BRANCH_PATTERN` and the dirty-tree check |
| No push / PR in dry run | `git_fix.py` reads `DRY_RUN` (default `true`) |
| Human approval before commit | `AskUserQuestion` step + `git_fix.py commit` requires `--approved-by-user` flag; Claude Code's own permission prompt for Bash is a second gate |
| Retry limit | Stated in SKILL.md; `git_fix.py` can also count attempts in `.git/ai-fix-state.json` |

## 5. Implementation steps

1. Copy `demo-java-app/` (clean, from the last commit) into the new project.
2. Port `sources.py` → `scripts/list_findings.py` with an argparse CLI.
3. Port the MCP tools → `scripts/run_tests.py` and `scripts/git_fix.py` (subcommands), same checks,
   JSON output, non-zero exit on refusal.
4. Move `SYSTEM_PROMPT` rules → `references/fix-rules.md`; PR body → `references/pr-template.md`;
   write `rule-playbooks.md` for the three demo rules.
5. Write `SKILL.md` (frontmatter + procedure above).
6. Add `hooks/guard_writes.py` and register it in `.claude/settings.json`.
7. Update `setup_demo.sh` and `README.md` (how to run: `/code-quality-fix file 3`).
8. Test: run the skill on the demo app with `DRY_RUN=true`; check all three findings reach a green
   build, a reject leaves no branch changes, and the hook blocks a write to `pom.xml`.
9. (Optional) Package as a plugin; keep the MCP server as an alternative tool backend.

## 6. Trade-offs to know

- **Less deterministic:** the order of steps is followed by Claude, not enforced by a graph.
  The scripts and hook make the *dangerous* steps deterministic; that is where it matters.
- **No API key or Python deps**, and the user can steer mid-run ("skip this one", "use a
  different approach").
- **Unattended / CI runs** are better served by the original agent, or by running the skill with
  `claude -p` in headless mode, where approval must come from the PR review instead.
