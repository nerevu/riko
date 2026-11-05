"""
Requires the user-level agent types the repo's skills spawn.

Usage:
    python .claude/skills/land/require_agents.py

The skills launch `auditor` (read-only sweeps) and `implementer` (code-changing work
orders) subagents. Their definitions live in ``~/.claude/agents/``, outside the repo, so
a fresh clone or another machine lacks them and the Agent call fails. It exits 0 when
every definition exists and grants at least the tools listed here; otherwise it prints
what to create and exits 1.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

AGENTS_DIR = Path.home() / ".claude" / "agents"
REQUIRED: dict[str, frozenset[str]] = {
    "auditor": frozenset({"Bash", "Read"}),
    "implementer": frozenset({"Bash", "Read", "Edit", "Write"}),
}


def get_problems(agents_dir: Path = AGENTS_DIR) -> list[str]:
    """Gets each missing agent definition or missing tool grant."""
    problems = []

    for name, tools in REQUIRED.items():
        path = agents_dir / f"{name}.md"

        if path.is_file():
            found = re.search(r"(?m)^tools:\s*(.+)$", path.read_text())
            granted = set() if found is None else set(re.split(r"[,\s]+", found[1]))

            if missing := sorted(tools - granted):
                problems.append(f"{path}: grant the tools {', '.join(missing)}")
        else:
            needed = ", ".join(sorted(tools))
            problems.append(f"{path} is missing: define agent {name!r} ({needed})")

    return problems


def main() -> int:
    """Prints the agent setup problems and returns the exit status."""
    problems = get_problems()

    for problem in problems:
        print(problem, file=sys.stderr)

    if problems:
        print(
            "The repo's skills spawn these user-level agents; copy the definitions "
            "from a maintainer's ~/.claude/agents/.",
            file=sys.stderr,
        )

    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
