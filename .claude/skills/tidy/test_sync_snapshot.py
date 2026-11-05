"""
Smoke-tests sync_snapshot.py on a throwaway git repo of snapshots and sources.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_sync_snapshot.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import inspiration_drift
import sync_snapshot

HEADER = b"---\nsource: ../proj/README.md\n---\n\n"
BODY = b"# proj\n\nText.\n"


def _git(repo: Path, *args: str) -> None:
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, *args], check=True)


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    snapshots = tmp_path / "inspiration"
    snapshots.mkdir()
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "README.md").write_bytes(BODY)
    (snapshots / "proj.md").write_bytes(HEADER + BODY)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    monkeypatch.setattr(inspiration_drift, "_INSPIRATION", snapshots)
    return snapshots


def test_install_keeps_header_and_strips_whitespace(
    tree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    candidate = tree.parent / "candidate.md"
    candidate.write_bytes(b"# proj  \n\nNew text.\t\n")
    argv = ["sync_snapshot.py", "install", "proj", str(candidate)]
    monkeypatch.setattr(sys, "argv", argv)
    assert sync_snapshot.main() == 0
    assert (tree / "proj.md").read_bytes() == HEADER + b"# proj\n\nNew text.\n"
    assert capsys.readouterr().out.startswith("== proj.md: 0\n")


def test_install_refuses_headerless_snapshot(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tree / "bare.md").write_bytes(BODY)
    candidate = tree.parent / "candidate.md"
    candidate.write_bytes(b"# new\n")
    argv = ["sync_snapshot.py", "install", "bare.md", str(candidate)]
    monkeypatch.setattr(sys, "argv", argv)
    assert sync_snapshot.main() == 2
    assert (tree / "bare.md").read_bytes() == BODY


@pytest.mark.parametrize(
    "names", [pytest.param(["proj.md"], id="named"), pytest.param([], id="staged")]
)
def test_copyback_writes_staged_body(
    tree: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    names: list[str],
) -> None:
    (tree / "proj.md").write_bytes(HEADER + b"# staged\n")
    _git(tree, "add", "proj.md")
    (tree / "proj.md").write_bytes(HEADER + b"# unstaged\n")
    monkeypatch.setattr(sys, "argv", ["sync_snapshot.py", "copyback", *names])
    assert sync_snapshot.main() == 1
    assert (tree.parent / "proj" / "README.md").read_bytes() == b"# staged\n"
    out = capsys.readouterr().out
    assert out.startswith("proj.md -> ")
    assert "proj.md: differs (" in out
