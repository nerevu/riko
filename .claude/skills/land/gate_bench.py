"""
Times ``/land``'s read-only gates serially and side by side.

Usage:
    python .claude/skills/land/gate_bench.py [--mode serial|concurrent|both]
        [--workers N]

Run it from the repository root in the active environment after any change to a
gate's command, to see whether the change holds on the current tree. It runs lint,
check-types, verify-types, and the suite (pytest-xdist with ``--workers``, default
``auto``) in each chosen mode (default both) and prints one
``<mode> <gate> rc=<code> <seconds>s`` line per gate plus the mode's wall time.
Each gate's log goes to a fresh temporary folder, printed first. It leaves out
prettify and codegen and runs the suite without ``--ratchet``, so it never records a
gate marker, never edits the tree, and never touches the coverage ceiling in
``pyproject.toml``.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MANAGE = "uv run --active python -m riko.cli.manage"
MODES = ("serial", "concurrent")


def build_gates(log_dir: Path, workers: str) -> dict[str, list[str]]:
    """Builds each read-only gate's command."""
    manage = shlex.split(MANAGE)
    report = log_dir / "coverage.json"
    return {
        "lint": [*manage, "lint", "--all"],
        "check-types": [*manage, "lint", "--check-types"],
        "verify-types": [*manage, "lint", "--verify-types"],
        "test": [
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--cov=riko",
            f"--cov-report=json:{report}",
            "-n",
            workers,
        ],
    }


def time_gate(name: str, command: list[str], log_dir: Path) -> tuple[str, int, float]:
    """Runs one gate with its output in ``log_dir`` and returns its timing."""
    start = time.perf_counter()

    with open(log_dir / f"{name}.log", "w") as log:
        env = {**os.environ, "COVERAGE_FILE": str(log_dir / ".coverage")}
        code = subprocess.run(
            command, stdout=log, stderr=subprocess.STDOUT, check=False, env=env
        ).returncode

    return name, code, time.perf_counter() - start


def bench(mode: str, gates: dict[str, list[str]], log_dir: Path) -> None:
    """Times the gates in one mode and prints a line per gate plus the wall time."""
    start = time.perf_counter()

    if mode == "serial":
        results = [time_gate(name, cmd, log_dir) for name, cmd in gates.items()]
    else:
        with ThreadPoolExecutor(len(gates)) as pool:
            futures = [pool.submit(time_gate, n, c, log_dir) for n, c in gates.items()]
            results = [future.result() for future in futures]

    for name, code, seconds in results:
        print(f"{mode:10} {name:13} rc={code} {seconds:6.1f}s")

    print(f"{mode:10} {'wall':13}      {time.perf_counter() - start:6.1f}s")


def main() -> None:
    """Parses the options and runs the chosen modes."""
    parser = argparse.ArgumentParser(description="Time the read-only land gates.")
    parser.add_argument("--mode", choices=(*MODES, "both"), default="both")
    parser.add_argument("--workers", default="auto")
    args = parser.parse_args()
    log_dir = Path(tempfile.mkdtemp(prefix="gate-bench-"))
    gates = build_gates(log_dir, args.workers)
    print(f"logs: {log_dir}")

    for mode in MODES if args.mode == "both" else (args.mode,):
        bench(mode, gates, log_dir)


if __name__ == "__main__":
    main()
