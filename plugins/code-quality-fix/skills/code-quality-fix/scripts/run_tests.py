#!/usr/bin/env python3
"""
Run the Maven build with unit tests in the target repo.

  python3 run_tests.py [--repo PATH]

Prints JSON {passed, exit_code, output_tail}. The command is fixed (`mvn -B -q test`);
nothing from the caller is passed to Maven.
"""
from __future__ import annotations

import argparse
import json
import subprocess

from common import BUILD_TIMEOUT_SEC, MAVEN_CMD, repo_root, run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    repo = repo_root(ap.parse_args().repo)
    try:
        r = run([MAVEN_CMD, "-B", "-q", "test"], repo, timeout=BUILD_TIMEOUT_SEC)
        output = (r.stdout + "\n" + r.stderr).strip()
        tail = "\n".join(output.splitlines()[-80:])
        result = {"passed": r.returncode == 0, "exit_code": r.returncode, "output_tail": tail}
    except subprocess.TimeoutExpired:
        result = {"passed": False, "exit_code": -1, "output_tail": f"Build timed out after {BUILD_TIMEOUT_SEC}s"}
    except FileNotFoundError:
        result = {"passed": False, "exit_code": -1, "output_tail": f"Maven not found: {MAVEN_CMD}"}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
