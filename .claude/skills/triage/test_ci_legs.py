"""
Smoke-tests ci_legs.py's per-leg sync commands and summary line.

Run after editing ci_legs.py:

    uv run --active pytest .claude/skills/triage/test_ci_legs.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import ci_legs


def _record(monkeypatch, stdout="", stderr="", returncode=0):
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs["env"]))
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    monkeypatch.setattr(ci_legs.subprocess, "run", run)
    monkeypatch.setenv("VIRTUAL_ENV", "/active")
    return calls


@pytest.mark.parametrize(
    ("leg", "extras"),
    [
        pytest.param("3.12-bare", [], id="bare"),
        pytest.param("3.13-extras", ["--all-extras"], id="extras"),
    ],
)
def test_sync_mirrors_the_ci_install(tmp_path, monkeypatch, leg, extras):
    calls = _record(monkeypatch)
    env = ci_legs.sync_leg(leg, tmp_path)
    sync, install = (cmd for cmd, _ in calls)
    python = leg.split("-")[0]
    assert sync == [
        "uv",
        "sync",
        "--locked",
        "--group",
        "dev",
        "-q",
        "-p",
        python,
        *extras,
    ]
    assert install[-2:] == ["-e", "."]
    assert env["UV_PROJECT_ENVIRONMENT"] == str(tmp_path / f"venv-{leg}")
    assert "VIRTUAL_ENV" not in env


@pytest.mark.parametrize(
    ("stdout", "stderr", "expected"),
    [
        pytest.param(
            ".F\n\n1 failed, 1 passed in 0.1s\n\n",
            "",
            "1 failed, 1 passed in 0.1s",
            id="tail",
        ),
        pytest.param("", "boom\n", "boom", id="stderr"),
    ],
)
def test_run_reports_the_tail_line(tmp_path, monkeypatch, stdout, stderr, expected):
    _record(monkeypatch, stdout, stderr, returncode=1)
    assert ci_legs.run_leg("3.12-bare", tmp_path, ["tests/x.py"]) == (expected, 1)
