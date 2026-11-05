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


def test_changed_tests_include_skill_tests(tmp_path, monkeypatch):
    def git(*args):
        config = ("-c", "user.name=t", "-c", "user.email=t@t")
        subprocess.run((fail_first.GIT, *config, *args), cwd=tmp_path, check=True)

    def write(name, text="x = 1\n"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)

    names = ["tests/test_a.py", ".claude/skills/land/test_b.py", ".claude/skills/x.py"]
    git("init", "-q")

    for name in names:
        write(name)

    git("add", ".")
    git("commit", "-q", "--no-verify", "-m", "base")

    for name in names:
        write(name, "x = 2\n")

    write(".claude/skills/triage/conftest.py")
    monkeypatch.setattr(fail_first, "ROOT_DIR", tmp_path)
    expected = [*sorted(names[:2]), ".claude/skills/triage/conftest.py"]
    assert fail_first.get_changed_tests("HEAD") == sorted(expected)


def test_snapshot_swaps_old_copies_into_the_working_tree(tmp_path, monkeypatch):
    def git(*args):
        config = ("-c", "user.name=t", "-c", "user.email=t@t")
        run = subprocess.run(
            (fail_first.GIT, *config, *args),
            cwd=tmp_path,
            check=True,
            text=True,
            capture_output=True,
        )
        return run.stdout

    git("init", "-q")
    (tmp_path / "fix.py").write_text("old\n")
    (tmp_path / "test_fix.py").write_text("t = 1\n")
    git("add", ".")
    git("commit", "-q", "--no-verify", "-m", "base")
    (tmp_path / "fix.py").write_text("new\n")
    (tmp_path / "test_fix.py").write_text("t = 2\n")
    monkeypatch.setattr(fail_first, "ROOT_DIR", tmp_path)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t")
    sha = fail_first.build_snapshot("HEAD", ["fix.py=HEAD:fix.py"])

    assert git("show", f"{sha}:fix.py") == "old\n"
    assert git("show", f"{sha}:test_fix.py") == "t = 2\n"
    assert git("status", "--short") == " M fix.py\n M test_fix.py\n"
