#!/usr/bin/env bash
# Set up the demo: copy the demo-java-app template into .work/demo-java-app (gitignored),
# make that copy its own git repo, and check it builds. The template itself is never modified.
#
#   ./setup_demo.sh           create the working copy if it does not exist
#   ./setup_demo.sh --reset   delete it and start again from the template
#
# No Python packages are needed: the skill's scripts use only the standard library.
set -euo pipefail
cd "$(dirname "$0")"

TEMPLATE=demo-java-app
WORK=.work/demo-java-app

if [ "${1:-}" = "--reset" ]; then
  rm -rf "$WORK" .claude/.ai-fix-active
  echo "Removed $WORK."
fi

if [ ! -d "$WORK/.git" ]; then
  rm -rf "$WORK"
  mkdir -p "$(dirname "$WORK")"
  cp -R "$TEMPLATE" "$WORK"
  rm -rf "$WORK/target"
  (
    cd "$WORK"
    git init -q -b main
    git config user.name  "demo"
    git config user.email "demo@example.com"
    git add .
    git commit -q -m "Seeded demo app with static-analysis findings"
  )
  echo "Created working copy $WORK (its own git repo)."
fi

(cd "$WORK" && mvn -B -q test) && echo "Demo app builds and its tests pass."

echo
echo "Next: open Claude Code in $(pwd) and run:  /code-quality-fix file 3"
