"""
Run a probe script against a released riko from PyPI.

Purpose: check a changelog claim ("before, X happened") against the release it compares
to, without touching the repo's environment. Creates a venv for the version in a fresh
``mktemp -d`` folder under ``--root``, installs ``riko[async]==VERSION``, and runs the
probe from that folder so the repo's ``riko`` never shadows it.

Inputs: ``VERSION`` (e.g. ``0.77.3``), ``PROBE`` (a Python file), ``--python`` (default
3.12; pre-2026 releases need 3.8), ``--build-pin`` (repeatable, e.g. ``setuptools<58``,
``cython<3``, which old feedparser/pyyaml sdists need), ``--root`` (default: the system
temp dir; pass the session scratchpad).

Outputs: the probe's stdout/stderr and exit code, plus the venv path on stderr so later
probes can run its ``bin/python`` directly.

Origin: 2026-11-13 changelog-verification session, where v0.77.3 and v0.66.0 were
installed by hand (the latter needed Python 3.8 and two build pins after three failed
attempts).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

UV = shutil.which("uv") or "uv"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a probe against a released riko.")
    parser.add_argument("version")
    parser.add_argument("probe", type=Path)
    parser.add_argument("--python", default="3.12")
    parser.add_argument("--build-pin", action="append", default=[])
    parser.add_argument("--root", type=Path, default=Path(tempfile.gettempdir()))
    args = parser.parse_args()
    home = Path(tempfile.mkdtemp(prefix=f"riko-{args.version}-", dir=args.root))
    venv, python = home / ".venv", home / ".venv" / "bin" / "python"
    subprocess.run([UV, "venv", "-q", "-p", args.python, str(venv)], check=True)
    install = [UV, "pip", "install", "-q", "-p", str(python)]

    if args.build_pin:
        pins = home / "build-pins.txt"
        pins.write_text("\n".join(args.build_pin) + "\n")
        install += ["--build-constraints", str(pins)]

    subprocess.run([*install, f"riko[async]=={args.version}"], check=True)
    print(f"venv: {venv}", file=sys.stderr)
    probe = str(args.probe.resolve())
    return subprocess.run([str(python), probe], cwd=home, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
