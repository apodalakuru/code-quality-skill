---
name: code-quality-fix
description: Fix SonarQube / CodeQL static-analysis findings in a Java Maven project, one finding at a time - smallest safe change plus a JUnit 5 test, verified by a green Maven build, retried on failure, and committed or turned into a PR only after the user approves the diff. Use when the user asks to fix, remediate, clear or work through Sonar, CodeQL, code-scanning or static-analysis findings/alerts in a Java codebase.
argument-hint: "[file|sonar|codeql] [max-findings] [repo-path]"
allowed-tools: Read, Glob, Grep, Edit, Write, AskUserQuestion, Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/list_findings.py *), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/run_tests.py), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/run_tests.py *), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/git_fix.py start-session *), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/git_fix.py start-branch *), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/git_fix.py diff), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/git_fix.py discard), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/git_fix.py finish *), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/git_fix.py summary), Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/git_fix.py end-session)
---

# Code-quality remediation

You fix static-analysis findings the way a careful senior Java engineer would: one finding at a
time, with the build as the judge and the user as the approver. You never commit, push or open a
PR on your own judgment.

Scripts (run from the project root, one command per shell call, never chained). `S` is this
skill's `scripts/` folder: `${CLAUDE_SKILL_DIR}/scripts`. If that text was not replaced by a real
path (outside Claude Code), use the absolute path of the `scripts/` folder next to this SKILL.md.

```
S=${CLAUDE_SKILL_DIR}/scripts
python3 $S/list_findings.py --source <file|sonar|codeql> --min-severity MAJOR --max 5 [--repo PATH]
python3 $S/run_tests.py [--repo PATH]
python3 $S/git_fix.py [--repo PATH] start-session|start-branch|diff|discard|ship|finish|summary|end-session
```

Write the full path out in every command (`python3 /abs/path/to/scripts/git_fix.py ...`); the
shell does not keep variables between calls. Every script prints JSON; `"ok": false` means a
guardrail refused the action. Read the `error`, and never work around it.

## Arguments

`$ARGUMENTS` may give: the source (`file` by default, or `sonar`, `codeql`), the maximum number
of findings (default 5), and a repo path (default `REPO_ROOT`, else `./.work/demo-java-app` if it exists, else the current directory). If you pass
a repo path, add `--repo PATH` to every script call.

## Procedure

### 1. Start
1. `git_fix.py start-session --base <BASE_BRANCH or main>`. If it refuses because the tree is dirty,
   stop and tell the user. Do not clean their work.
2. `list_findings.py ...`. If the list is empty, run `end-session`, say so, and stop.
3. Show the findings as a short table (severity, rule, file:line, message) and say whether
   `dry_run` is on (from the start-session output).

### 2. For each finding, most severe first
**a. Branch:** `git_fix.py start-branch --rule <rule> --id <id> --file <file>`.

**b. Read the context:** the source file, and its test at the same path under `src/test/java` with
`Test.java` appended (it may not exist yet). Also read collaborators if you need them. Read
[references/fix-rules.md](references/fix-rules.md) once per session, and the matching section of
[references/rule-playbooks.md](references/rule-playbooks.md) if the rule is listed there.

**c. Fix:** edit only `.java` files under `src/main/java` and `src/test/java` (a hook blocks
anything else). Follow fix-rules.md: make the smallest change, add a JUnit 5 test that fails
without the fix where practical, use synthetic data only, and add no new dependencies.

**d. Build:** `run_tests.py`.
- `passed: true`: go to step e.
- `passed: false`: read `output_tail` carefully and work out the root cause. Then
  `git_fix.py discard`, `git_fix.py start-branch ...` (same arguments), and make a corrected change.
  `start-branch` counts attempts and refuses after the limit (3 by default). When it refuses, run
  `git_fix.py finish --status failed --detail "<one line: why it still fails>"` and move on.

**e. Review: this step is mandatory.**
1. `git_fix.py diff`. If `disallowed_changes` is not empty, discard and redo the attempt.
2. Show the user, in this order:
   - **Finding:** `<SEVERITY> <rule> in <file>:<line>`: message
   - **Fix:** 2-4 sentences on what was wrong and how the change fixes it
   - **Test:** which test proves it and what it asserts
   - **Risk:** low / medium / high, with a reason
   - **Attempts:** n
   - the full diff in a ```diff block
3. Ask with AskUserQuestion (if your tool has no such tool, ask in chat and wait for an explicit
   answer; silence or ambiguity is not approval): "Approve this fix for `<rule>` in `<File>.java`?". Give the options
   **Approve** (commit on the ai-fix branch, and push + PR unless dry run), **Reject** (discard it),
   and **Skip remaining** (discard it and stop). The user's free-text note is the reviewer comment.

**f. Act on the answer:**
- **Approve:** build the PR body from
  [references/pr-template.md](references/pr-template.md), then run
  `git_fix.py ship --approve <approval_code from step e> --title "fix(<source>): <rule> in <File>.java" --body "<body>"`.
  Report the `detail` it returns (the PR URL, or the dry-run commit).
- **Reject:** `git_fix.py finish --status rejected --detail "<reviewer comment or 'rejected by reviewer'>"`.
- **Skip remaining:** `finish --status rejected ...` for this finding, then go to step 3.

Never call `ship` unless the user chose Approve **in this step, for this diff**. If you change
anything after approval, the approval code no longer matches and you must review again.

### 3. Finish
`git_fix.py end-session`. Print a summary table (status, rule, file, detail). If dry run was on,
tell the user how to inspect the branches: `git -C <repo> log --oneline --all` and
`git -C <repo> diff main ai-fix/<...>`.

## If something goes wrong
- A script refused an action: report it and do not retry it another way. Do not run git directly,
  edit files outside the allowed folders, or change the build to make a test pass.
- The fix needs a non-Java change (pom.xml, configuration, a new dependency): do not make it.
  Run `finish --status skipped --detail "<what is needed>"` and tell the user.
- The user interrupts or changes their mind: run `git_fix.py discard` if an attempt is in progress,
  then `end-session`.
