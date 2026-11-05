"""
List CLI flags and PowerShell parameters a readme cites that its repo never defines.

Purpose: catch stale readme invocations (wrong flags, renamed ``-Params``), the most
common mechanical finding of the inspiration-readme audit (365-admin, entra-id-sso,
ckanny, ...).

Inputs: ``readme`` = readme path; ``repo`` = source repo root.

Outputs: one line per readme token with no literal match in any repo source file
(``.py``/``.ps1``/``.psm1``/``.js``/``.sh``, extensionless scripts), skipping venvs
and ``node_modules``, or ``no missing flags``; exit 1 when any token is missing.
Leads only: a hit still needs a read, and flags built dynamically are missed.

Origin: 2026-11-04 inspiration-readme audit.
"""

import argparse
import re
import sys
from pathlib import Path

_SKIP = {"node_modules", ".git", ".venv", "venv", "__pycache__"}
_EXTS = {".py", ".ps1", ".psm1", ".js", ".sh", ""}
_FLAG = re.compile(r"(?<![\w/-])(--[a-z][\w-]+|-[A-Z][A-Za-z0-9]+)\b")


def _corpus(repo: Path) -> str:
    return "\n".join(
        path.read_text(errors="ignore")
        for path in repo.rglob("*")
        if path.is_file() and path.suffix in _EXTS and not _SKIP & set(path.parts)
    )


def load_missing(readme: Path, repo: Path) -> list[str]:
    """Loads the readme's flags that no repo source file spells out."""
    corpus = _corpus(repo)
    tokens = sorted(set(_FLAG.findall(readme.read_text())))
    return [token for token in tokens if token.lstrip("-") not in corpus]


def main() -> int:
    parser = argparse.ArgumentParser(description="List readme flags a repo lacks.")
    parser.add_argument("readme", type=Path)
    parser.add_argument("repo", type=Path)
    args = parser.parse_args()
    missing = load_missing(args.readme, args.repo)
    print("\n".join(missing) or "no missing flags")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
