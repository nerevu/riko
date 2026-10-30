"""
Smoke-tests gates.py on a throwaway repository.

Run after editing gates.py:

    uv run --active pytest .claude/skills/land/test_gates.py
"""

from __future__ import annotations

import fcntl
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import gates


@pytest.fixture
def repo(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(
            [gates.GIT, *args], cwd=tmp_path, check=True, capture_output=True
        )

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / ".gitignore").write_text(".claude/\n")
    (tmp_path / "a.py").write_text("a = 1\n")
    git("add", "-A")
    git("commit", "-qm", "init")
    monkeypatch.chdir(tmp_path)
    return git


def test_tree_id_ignores_staging_and_commits_but_not_edits(repo, tmp_path):
    before = gates.get_tree_id()
    (tmp_path / "b.py").write_text("b = 2\n")
    untracked = gates.get_tree_id()
    repo("add", "b.py")
    staged = gates.get_tree_id()
    repo("commit", "-qm", "b")
    committed = gates.get_tree_id()
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "ignored.txt").write_text("x")

    assert untracked != before
    assert untracked == staged == committed == gates.get_tree_id()


@pytest.mark.usefixtures("repo")
def test_run_records_then_skips_until_the_tree_changes(tmp_path, capsys):
    path = gates.get_state_dir() / "gate-markers.json"
    marker = tmp_path / "ran"
    command = ["sh", "-c", f"echo x >> {marker}"]

    assert gates.check(path, "lint") == 1
    assert gates.run(path, "lint", command, mutates=False, lock=False) == 0
    assert gates.check(path, "lint") == 1  # the command itself edited the tree
    marker.write_text("")
    command = ["true"]
    assert gates.run(path, "lint", command, mutates=False, lock=False) == 0
    assert gates.check(path, "lint") == 0
    (tmp_path / "a.py").write_text("a = 2\n")
    assert gates.check(path, "lint") == 1
    assert "not recorded lint" in capsys.readouterr().out


@pytest.mark.usefixtures("repo")
def test_check_prints_the_diff_since_the_last_pass(tmp_path, capsys):
    path = gates.get_state_dir() / "gate-markers.json"
    gates.run(path, "tidy", ["true"], mutates=False, lock=False)
    passed = gates.get_tree_id()
    (tmp_path / "a.py").write_text("a = 2\n")
    capsys.readouterr()

    assert gates.check(path, "tidy") == 1
    expected = f"changed since: git diff {passed} {gates.get_tree_id()}"
    assert expected in capsys.readouterr().out


@pytest.mark.usefixtures("repo")
def test_scope_prints_edits_and_untracked_files_since_the_pass(tmp_path, capsys):
    path = gates.get_state_dir() / "gate-markers.json"
    gates.run(path, "tidy", ["true"], mutates=False, lock=False)
    (tmp_path / "a.py").write_text("a = 2\n")
    (tmp_path / "c.py").write_text("c = 3\n")
    (tmp_path / "uv.lock").write_text("lock\n")
    capsys.readouterr()

    assert gates.scope(path, "tidy") == 1
    out = capsys.readouterr().out
    assert out.startswith("scope tidy: edits since the pass at ")
    assert "+a = 2" in out
    assert "+c = 3" in out
    assert "c.py" in out.split("--- untracked")[1]
    assert "uv.lock" not in out.split("--- diff")[1]
    assert gates.main(["record", "tidy"]) == 0
    assert gates.scope(path, "tidy") == 0


@pytest.mark.usefixtures("repo")
def test_scope_falls_back_to_the_head_and_reports_an_empty_scope(tmp_path, capsys):
    path = gates.get_state_dir() / "gate-markers.json"

    assert gates.scope(path, "tidy") == gates.EMPTY
    assert "scope tidy: the working tree\nbase: HEAD\n" in capsys.readouterr().out
    (tmp_path / "a.py").write_text("a = 2\n")
    assert gates.scope(path, "tidy", max_inline=3) == 1
    out = capsys.readouterr().out
    target = path.with_name("tidy-scope.diff")
    assert f"written to {target}" in out
    assert "+a = 2" in target.read_text()


@pytest.mark.usefixtures("repo")
def test_mutating_gate_records_the_tree_it_left(tmp_path):
    path = gates.get_state_dir() / "gate-markers.json"
    command = ["sh", "-c", f"echo 'a = 3' > {tmp_path / 'a.py'}"]

    assert gates.run(path, "prettify", command, mutates=True, lock=False) == 0
    assert gates.check(path, "prettify") == 0


@pytest.mark.usefixtures("repo")
def test_failed_command_records_nothing():
    path = gates.get_state_dir() / "gate-markers.json"

    assert gates.run(path, "test", ["false"], mutates=False, lock=False) == 1
    assert gates.check(path, "test") == 1


@pytest.mark.usefixtures("repo")
def test_locked_run_reports_busy_without_waiting():
    path = gates.get_state_dir() / "gate-markers.json"

    with open(gates.get_lock_path(), "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        code = gates.run(path, "test", ["true"], mutates=False, lock=True)

    assert code == gates.BUSY
    assert gates.get_lock_path().parent.name == ".git"
    assert gates.run(path, "test", ["true"], mutates=False, lock=True) == 0


@pytest.mark.usefixtures("repo")
def test_cli_reads_flags_after_the_gate_and_the_command_after_the_separator():
    argv = ["run", "lint", "--lock", "--", "sh", "-c", "exit 3"]

    assert gates.main(argv) == 3
    assert gates.main(["run", "lint", "--lock", "--", "true"]) == 0
    assert gates.main(["check", "lint"]) == 0


@pytest.mark.usefixtures("repo")
def test_run_keeps_the_last_pytest_summary_line(capsys):
    path = gates.get_state_dir() / "gate-markers.json"
    output = "== 1 passed in 1s ==\\n=== 3 passed, 2 xfailed in 9s ===\\nratchet ok\\n"
    command = ["printf", output]

    assert gates.print_summary(path, "test") == 1
    assert gates.run(path, "test", command, mutates=False, lock=False) == 0
    assert "ratchet ok" in capsys.readouterr().out
    assert gates.print_summary(path, "test") == 0
    assert capsys.readouterr().out.startswith("3 passed, 2 xfailed in 9s (current;")
