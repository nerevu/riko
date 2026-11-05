"""
List lines of a snapshot's committed version whose words are mostly absent from it now.

Purpose: catch content a readme rewrite dropped (prose, table rows/columns, lists,
code), so intended-state material is restored rather than lost. Each snapshot in
``_docs/research/inspiration/`` is compared against its ``HEAD`` version, both
without the ``source:`` header; a committed line of three or more words is a
suspect when at least 40% of its words appear nowhere in the working copy.

Inputs: one or more snapshot names with extension (``ams.md``, ``lego.rst``); a bare
name means ``.md``. A path is reduced to its file name, so it runs from any cwd.

Outputs: per snapshot, ``== <name>: N`` then one line per suspect with the missing
words. Leads only: a reworded line can appear although its content survived, so it
always exits 0. A snapshot absent from ``HEAD`` reports 0.

Origin: 2026-11-04 inspiration-readme rewrite.
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import inspiration_drift

_GIT = shutil.which("git") or "git"
_WORD = re.compile(r"[\w.$/-]{3,}")
_MIN_WORDS = 3
_THRESHOLD = 0.4
_SHOWN_WORDS = 6
_SHOWN_CHARS = 120


def resolve_snapshot(name: str) -> Path:
    """Resolves a snapshot argument to its path under the inspiration directory."""
    base = Path(name).name
    file_name = base if base.endswith((".md", ".rst")) else f"{base}.md"
    return inspiration_drift._INSPIRATION / file_name


def _body(data: bytes) -> str:
    _, body = inspiration_drift._split_bytes(data)
    return body.decode("utf-8", "replace")


def _committed(snapshot: Path) -> bytes:
    result = subprocess.run(
        [_GIT, "-C", str(snapshot.parent), "show", f"HEAD:./{snapshot.name}"],
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else b""


def load_leads(snapshot: Path) -> list[str]:
    """Loads one report line per committed line the working copy mostly lacks."""
    words = set(_WORD.findall(_body(snapshot.read_bytes()).lower()))
    leads: list[str] = []

    for line in _body(_committed(snapshot)).splitlines():
        tokens = _WORD.findall(line.lower())
        missing = [token for token in tokens if token not in words]

        if len(tokens) >= _MIN_WORDS and len(missing) / len(tokens) >= _THRESHOLD:
            shown = " ".join(missing[:_SHOWN_WORDS])
            text = line.strip()[:_SHOWN_CHARS]
            leads.append(f"  [{len(missing)}/{len(tokens)} missing: {shown}] {text}")

    return leads


def print_leads(snapshot: Path) -> None:
    """Prints the removed-content report for one snapshot."""
    if snapshot.is_file():
        leads = load_leads(snapshot)
        print(f"== {snapshot.name}: {len(leads)}")
        sys.stdout.writelines(f"{lead}\n" for lead in leads)
    else:
        print(f"== {snapshot.name}: no such snapshot")


def main() -> int:
    parser = argparse.ArgumentParser(description="List content a rewrite removed.")
    parser.add_argument("names", nargs="+", metavar="snapshot")
    args = parser.parse_args()

    for name in args.names:
        print_leads(resolve_snapshot(name))

    return 0


if __name__ == "__main__":
    sys.exit(main())
