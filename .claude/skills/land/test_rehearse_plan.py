"""
Smoke-tests rehearse_plan.py's full checks on a throwaway tree.

Run after editing rehearse_plan.py:

    uv run --active pytest .claude/skills/land/test_rehearse_plan.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import rehearse_plan


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Starts a ``topic`` branch off ``next`` and returns ``(git, commit)``."""

    def git(*args):
        config = ("-c", "user.name=t", "-c", "user.email=t@t")
        cmd = ("git", *config, "-c", "core.hooksPath=/dev/null", *args)
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout

    def commit(path, text, *args):
        (tmp_path / path).write_text(text)
        git("add", path)
        git("commit", "-q", *args)
        return git("rev-parse", "HEAD").strip()

    monkeypatch.chdir(tmp_path)
    git("init", "-q", "-b", "next")
    commit("f", "1\n2\n3\n", "-m", "base")
    git("checkout", "-q", "-b", "topic")
    return git, commit


@pytest.mark.parametrize("skills", [True, False])
def test_skill_steps_run_the_skill_smoke_tests(tmp_path, monkeypatch, skills):
    labels = []
    record = lambda _root, commands: labels.extend(c[0] for c in commands) or "ok"
    monkeypatch.setattr(rehearse_plan, "run_checks", record)
    rehearse_plan.check(tmp_path, full=False, skills=skills)
    assert ("skill-tests" in labels) is skills


def test_rewritten_fixup_target_names_its_replacement(repo):
    _, commit = repo
    old = commit("g", "b\n", "-m", "second")
    new = commit("g", "c\n", "--amend", "-m", "second")
    step = rehearse_plan.Step("fixup", old)

    with pytest.raises(SystemExit, match=f"not in HEAD's history; .* now {new[:8]}"):
        rehearse_plan.require_targets([step])


def test_autosquash_moves_older_pending_fixups(repo):
    git, commit = repo
    first = commit("f", "a\n2\n3\n", "-m", "first")
    second = commit("g", "b\n", "-m", "second")
    commit("f", "a\nx\n3\n", f"--fixup={first}")
    commit("f", "a\ny\n3\n", f"--fixup={second}")
    planned = commit("g", "c\n", f"--fixup={second}")
    tree = git("rev-parse", f"{planned}^{{tree}}").strip()
    step = rehearse_plan.Step("fixup", second, commit=planned, tree=tree)

    assert rehearse_plan.rehearse_autosquash([step]) == "ok"
