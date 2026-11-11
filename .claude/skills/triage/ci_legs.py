"""
Run pytest targets in scratch venvs that mirror CI's test-matrix legs.

Purpose: reproduce a failure that only one CI leg shows (no extras, or a Python
other than the local 3.12) without touching the active environment. Each leg gets
a cached venv under the scratch root, synced the way `.github/workflows/ci.yml`
syncs it, with riko installed editable from this checkout. Tests run through
`python -m pytest` (never the `manage` script, which can resolve to mezmorize's).

Inputs:
    --legs      comma list of LEG ids, `<python>-<extras|bare>` (default
                `3.12-bare,3.13-extras`, two of the five legs a local 3.12
                all-extras venv never exercises)
    --root      scratch directory that holds the venvs (default: $TMPDIR/riko-ci-legs)
    targets     pytest node ids or paths (default: the whole configured suite)

Outputs: one summary line per leg (`leg: <pytest tail line>`), exit 1 when any
leg fails.

Origin: 2026-11-11 /triage of CI doctest failures (feedparser vs fastfeedparser
entry keys, Python 3.13 TypeError suggestions, a 3.13-only unraisable warning),
where the matching venvs were built and driven by hand several times.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from riko.base._paths import ROOT_DIR

DEFAULT_LEGS = "3.12-bare,3.13-extras"


def sync_leg(leg: str, root: Path) -> dict[str, str]:
    """Syncs ``leg``'s cached venv as CI does; returns the env that selects it."""
    python, kind = leg.split("-")
    venv = root / f"venv-{leg}"
    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(venv)}
    env.pop("VIRTUAL_ENV", None)
    extras = ["--all-extras"] if kind == "extras" else []
    sync = ["uv", "sync", "--locked", "--group", "dev", "-q", "-p", python, *extras]
    subprocess.run(sync, cwd=ROOT_DIR, env=env, check=True)
    install = ["uv", "pip", "install", "-q", "--reinstall", "--no-deps", "-e", "."]
    subprocess.run(install, cwd=ROOT_DIR, env=env, check=True)
    return env


def run_leg(leg: str, root: Path, targets: list[str]) -> tuple[str, int]:
    """Runs pytest in ``leg``'s venv; returns its tail line and exit code."""
    env = sync_leg(leg, root)
    cmd = ["uv", "run", "--no-sync", "python", "-m", "pytest", "--no-cov", "-q"]
    cmd += ["-p", "no:cacheprovider", *targets]
    proc = subprocess.run(
        cmd, cwd=ROOT_DIR, env=env, check=False, capture_output=True, text=True
    )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    return (lines[-1] if lines else proc.stderr.strip()[-200:]), proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run pytest in CI-leg venvs.")
    parser.add_argument("--legs", default=DEFAULT_LEGS)
    default_root = Path(tempfile.gettempdir()) / "riko-ci-legs"
    parser.add_argument("--root", type=Path, default=default_root)
    parser.add_argument("targets", nargs="*")
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    codes: list[int] = []

    for leg in args.legs.split(","):
        summary, code = run_leg(leg, args.root, args.targets)
        print(f"{leg}: {summary}")
        codes.append(code)

    return int(any(codes))


if __name__ == "__main__":
    sys.exit(main())
