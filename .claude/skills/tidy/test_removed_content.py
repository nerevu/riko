"""
Smoke-tests removed_content.py on a throwaway git repo of snapshots.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_removed_content.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import inspiration_drift
import removed_content

HEADER = b"---\nsource: ../proj/README.md\n---\n\n"
OLD = b"# proj\n\nAlpha bravo charlie delta\nEcho foxtrot golf hotel\n"


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    snapshots = tmp_path / "inspiration"
    snapshots.mkdir()
    (snapshots / "proj.md").write_bytes(HEADER + OLD)
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "base"], check=True)
    monkeypatch.setattr(inspiration_drift, "_INSPIRATION", snapshots)
    return snapshots


@pytest.mark.parametrize(
    ("argv", "body", "expected"),
    [
        pytest.param(["proj"], OLD, ["== proj.md: 0"], id="unchanged"),
        pytest.param(
            ["proj.md"],
            b"# proj\n\nAlpha bravo charlie delta\n",
            ["== proj.md: 1", "  [4/4 missing: echo foxtrot golf hotel] Echo foxtrot"],
            id="dropped",
        ),
        pytest.param(
            ["../elsewhere/proj.md"],
            b"# proj\n\nAlpha bravo charlie delta\nEcho foxtrot golf\n",
            ["== proj.md: 0"],
            id="mostly-kept",
        ),
        pytest.param(["gone.rst"], OLD, ["== gone.rst: no such snapshot"], id="absent"),
    ],
)
def test_reports_leads(
    tree: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    body: bytes,
    expected: list[str],
) -> None:
    (tree / "proj.md").write_bytes(HEADER + body)
    monkeypatch.setattr(sys, "argv", ["removed_content.py", *argv])
    assert removed_content.main() == 0
    out = capsys.readouterr().out
    assert all(line in out for line in expected)


def test_uncommitted_snapshot_has_no_leads(
    tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tree / "new.rst").write_bytes(b".. source: ../new/README.rst\n\nnew\n")
    monkeypatch.setattr(sys, "argv", ["removed_content.py", "new.rst"])
    assert removed_content.main() == 0
    assert capsys.readouterr().out == "== new.rst: 0\n"
