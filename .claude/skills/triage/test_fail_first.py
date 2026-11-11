"""
Smoke-tests fail_first.py's choice of test files to overlay.

Run after editing fail_first.py:

    uv run --active pytest .claude/skills/triage/test_fail_first.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import fail_first


def _git(cwd, *args):
    config = ("-c", "user.name=t", "-c", "user.email=t@t")
    command = (fail_first.GIT, *config, *args)
    run = subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True)
    return run.stdout


def _set_identity(monkeypatch):
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "t")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "t@t")


def test_changed_tests_include_skill_tests(tmp_path, monkeypatch):
    def write(name, text="x = 1\n"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)

    names = ["tests/test_a.py", ".claude/skills/land/test_b.py", ".claude/skills/x.py"]
    _git(tmp_path, "init", "-q")

    for name in names:
        write(name)

    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "--no-verify", "-m", "base")

    for name in names:
        write(name, "x = 2\n")

    write(".claude/skills/triage/conftest.py")
    monkeypatch.setattr(fail_first, "ROOT_DIR", tmp_path)
    expected = [*sorted(names[:2]), ".claude/skills/triage/conftest.py"]
    assert fail_first.get_changed_tests("HEAD") == sorted(expected)


def test_snapshot_swaps_old_copies_into_the_working_tree(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q")
    (tmp_path / "fix.py").write_text("old\n")
    (tmp_path / "test_fix.py").write_text("t = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "--no-verify", "-m", "base")
    (tmp_path / "fix.py").write_text("new\n")
    (tmp_path / "test_fix.py").write_text("t = 2\n")
    monkeypatch.setattr(fail_first, "ROOT_DIR", tmp_path)
    _set_identity(monkeypatch)
    sha = fail_first.build_snapshot("HEAD", ["fix.py=HEAD:fix.py"])

    assert _git(tmp_path, "show", f"{sha}:fix.py") == "old\n"
    assert _git(tmp_path, "show", f"{sha}:test_fix.py") == "t = 2\n"
    assert _git(tmp_path, "status", "--short") == " M fix.py\n M test_fix.py\n"


def test_build_old_tree_keeps_swapped_test_files(tmp_path, monkeypatch):
    names = ["tests/test_a.py", "tests/test_b.py"]
    _git(tmp_path, "init", "-q")
    (tmp_path / "tests").mkdir()

    for name in names:
        (tmp_path / name).write_text("old\n")

    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "--no-verify", "-m", "base")

    for name in names:
        (tmp_path / name).write_text("new\n")

    monkeypatch.setattr(fail_first, "ROOT_DIR", tmp_path)
    _set_identity(monkeypatch)
    sha = fail_first.build_snapshot("HEAD", ["tests/test_a.py=HEAD:tests/test_a.py"])
    folder = fail_first.build_old_tree(sha, ["tests/test_a.py"])

    assert (folder / "tests/test_a.py").read_text() == "old\n"
    assert (folder / "tests/test_b.py").read_text() == "new\n"
