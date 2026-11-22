"""
Smoke-tests rehearse_plan.py's checks and split_hunks.py's listing on throwaway trees.

Run after editing rehearse_plan.py or split_hunks.py:

    uv run --active pytest .claude/skills/land/test_rehearse_plan.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import rehearse_plan
import split_hunks


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
    record = lambda _root, commands, _log=None: (
        labels.extend(c[0] for c in commands) or "ok"
    )
    monkeypatch.setattr(rehearse_plan, "run_checks", record)
    rehearse_plan.check(tmp_path, full=False, skills=skills)
    assert ("skill-tests" in labels) is skills


def test_failed_check_logs_its_output_and_quotes_the_errors(tmp_path):
    script = "print('a.md:1: error here'); print('Success!'); raise SystemExit(1)"
    command = ("lint", (sys.executable, "-c", script))
    result = rehearse_plan.run_checks(tmp_path, [command], tmp_path / "02")
    assert result == "lint: a.md:1: error here (log: 02.lint.log)"
    assert "Success!" in (tmp_path / "02.lint.log").read_text()


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


def test_hunk_list_shows_bodies(repo, capsys, monkeypatch):
    Path("f").write_text("1\ntwo\n3\n")
    monkeypatch.setattr(sys, "argv", ["split_hunks.py", "list", "--body", "1"])
    split_hunks.main()
    assert capsys.readouterr().out.splitlines() == [
        "f:2\t+1/-1\ttwo",
        "    -2",
        "    ...",
    ]


def test_hunk_list_reads_a_commit_with_head(repo, capsys, monkeypatch):
    _, commit = repo
    sha = commit("f", "1\ntwo\n3\n", "-m", "second")
    Path("f").write_text("dirty\n")
    argv = ["split_hunks.py", "list", "--base", f"{sha}^", "--head", sha]
    monkeypatch.setattr(sys, "argv", argv)
    split_hunks.main()
    split_hunks.set_head(None)
    assert capsys.readouterr().out.splitlines() == ["f:2\t+1/-1\ttwo"]


def fold(*specs, resolve=None, rewords=()):
    """Rehearses ``--fold`` specs both passes, as ``main`` does for a fold-only plan."""
    split_hunks.set_base("HEAD")
    split_hunks.set_head(None)
    folds = [rehearse_plan.parse_fold(spec) for spec in specs]
    words = []

    for sha, message in rewords:
        path = Path(tempfile.mkdtemp()) / "msg"
        path.write_text(message)
        words.append(rehearse_plan.Reword(sha, path))

    rehearse_plan.require_folds(folds, 0)
    rehearse_plan.require_rewords(words, folds)
    rehearsal = rehearse_plan.rehearse_folds(folds, resolve or {}, rewords=words)

    if not rehearsal.problem:
        rehearse_plan.rehearse_squash(rehearsal, rehearsal.first, resolve or {})

    return rehearsal, folds


def subjects(git, rehearsal):
    log = git("log", "--reverse", "--format=%s", f"{rehearsal.base}..{rehearsal.tip}")
    return log.splitlines()


def same_tree(git, rev):
    return git("rev-parse", f"{rev}^{{tree}}") == git("rev-parse", "HEAD^{tree}")


def test_whole_fold_drops_the_mover(repo):
    git, commit = repo
    target = commit("g", "a\n", "-m", "target")
    commit("h", "x\n", "-m", "middle")
    mover = commit("g", "b\n", "-m", "mover")
    rehearsal, _ = fold(f"{target}:{mover}")
    assert rehearsal.problem == ""
    assert same_tree(git, rehearsal.tip)
    assert subjects(git, rehearsal) == ["target", "middle"]


def test_partial_fold_splits_the_mover(repo):
    git, commit = repo
    target = commit("g", "p\nq\nr\ns\nt\n", "-m", "target")
    commit("h", "x\n", "-m", "middle")
    mover = commit("g", "P\nq\nr\ns\nT\n", "-m", "mover")
    rehearsal, _ = fold(f"{target}:{mover}@g:1")
    folded = git("rev-parse", f"{rehearsal.tip}~2").strip()
    assert same_tree(git, rehearsal.tip)
    assert subjects(git, rehearsal) == ["target", "middle", "mover"]
    assert git("show", f"{folded}:g") == "P\nq\nr\ns\nt\n"
    assert git("diff", "-U0", f"{rehearsal.tip}^", rehearsal.tip).count("@@") == 2


def test_fold_squashes_pending_fixups_in_the_same_pass(repo):
    git, commit = repo
    target = commit("g", "a\n", "-m", "target")
    other = commit("h", "x\n", "-m", "other")
    mover = commit("g", "b\n", "-m", "mover")
    commit("h", "y\n", f"--fixup={other}")
    rehearsal, _ = fold(f"{target}:{mover}")
    assert same_tree(git, rehearsal.tip)
    assert subjects(git, rehearsal) == ["target", "other"]


def test_moved_test_hunk_naming_a_kept_helper_is_reported(repo):
    _, commit = repo
    Path("tests").mkdir()
    target = commit(
        "tests/t.py", "import os\n\n\ndef test_a():\n    assert os\n", "-m", "t"
    )
    text = "import os\n\n\nclass Helper:\n    pass\n\n\ndef test_a():\n    assert os\n"
    text += "\n\ndef test_b():\n    assert Helper\n"
    mover = commit("tests/t.py", text, "-m", "mover")
    rehearsal, folds = fold(f"{target}:{mover}@tests/t.py:10")
    pairs = rehearse_plan.map_commits(rehearsal.base, "HEAD", rehearsal.tip)
    new = next(n for o, n in pairs if o == folds[0].target)
    hint = rehearse_plan.check_moved_tests(rehearse_plan.extract(new), folds)
    assert hint == (
        "undefined Helper from tests/t.py:10; to keep those in the mover, drop the "
        "fold; or also fold tests/t.py:4, which define them"
    )


def test_fold_conflict_without_a_pick_stops(repo):
    _, commit = repo
    target = commit("v", "1\n", "-m", "target")
    commit("v", "2\n", "-m", "middle")
    mover = commit("v", "3\n", "-m", "mover")
    rehearsal, _ = fold(f"{target}:{mover}")
    assert rehearsal.problem.startswith(f"CONFLICT applying {mover[:7]}")
    assert " in v; worktree " in rehearsal.problem


@pytest.mark.parametrize(("pick", "equal"), [("theirs", False), ("max", True)])
def test_fold_conflict_resolves_with_a_pick(repo, pick, equal):
    git, commit = repo
    target = commit("v", "1\n", "-m", "target")
    commit("v", "2\n", "-m", "middle")
    mover = commit("v", "3\n", "-m", "mover")
    rehearsal, _ = fold(f"{target}:{mover}", resolve={"v": pick})
    assert rehearsal.problem == ""
    assert same_tree(git, rehearsal.tip) is equal


def test_fold_rebase_starts_no_background_maintenance(repo, tmp_path, monkeypatch):
    _, commit = repo
    target = commit("v", "1\n", "-m", "target")
    commit("v", "2\n", "-m", "middle")
    mover = commit("v", "3\n", "-m", "mover")
    trace = tmp_path / "trace"
    monkeypatch.setenv("GIT_TRACE", str(trace))
    rehearsal, _ = fold(f"{target}:{mover}", resolve={"v": "theirs"})
    assert rehearsal.problem == ""
    assert "maintenance run" not in trace.read_text()


def test_fold_target_at_the_merge_point_is_refused(repo):
    git, commit = repo
    base = git("rev-parse", "next").strip()
    mover = commit("f", "1\n2\nx\n", "-m", "mover")

    with pytest.raises(SystemExit, match="at or before the merge point"):
        fold(f"{base}:{mover}")


def test_reword_replaces_a_branch_commit_message(repo):
    git, commit = repo
    first = commit("g", "a\n", "-m", "first")
    commit("h", "x\n", "-m", "second")
    rehearsal, _ = fold(rewords=[(first, "renamed\n\n- Also a body\n")])
    assert same_tree(git, rehearsal.tip)
    assert subjects(git, rehearsal) == ["renamed", "second"]
    assert git("log", "-1", "--format=%B", f"{rehearsal.tip}^").strip().endswith("body")


def test_reworded_fold_target_keeps_its_message_through_the_squash(repo):
    git, commit = repo
    target = commit("g", "p\nq\nr\ns\nt\n", "-m", "target")
    commit("h", "x\n", "-m", "middle")
    mover = commit("g", "P\nq\nr\ns\nT\n", "-m", "mover")
    rehearsal, _ = fold(f"{target}:{mover}@g:1", rewords=[(target, "new target\n")])
    assert same_tree(git, rehearsal.tip)
    assert subjects(git, rehearsal) == ["new target", "middle", "mover"]
    assert git("show", f"{rehearsal.tip}~2:g") == "P\nq\nr\ns\nt\n"


def test_reword_of_a_partial_mover_rewords_the_rest(repo):
    git, commit = repo
    target = commit("g", "p\nq\nr\ns\nt\n", "-m", "target")
    commit("h", "x\n", "-m", "middle")
    mover = commit("g", "P\nq\nr\ns\nT\n", "-m", "mover")
    rehearsal, _ = fold(f"{target}:{mover}@g:1", rewords=[(mover, "the rest\n")])
    pairs = rehearse_plan.map_commits(
        rehearsal.base, "HEAD", rehearsal.tip, rehearsal.renames
    )
    assert same_tree(git, rehearsal.tip)
    assert subjects(git, rehearsal) == ["target", "middle", "the rest"]
    assert git("diff", "-U0", f"{rehearsal.tip}^", rehearsal.tip).count("@@") == 2
    assert all(old and new for old, new in pairs)


def test_pending_fixup_of_a_reworded_commit_still_squashes(repo):
    git, commit = repo
    first = commit("g", "a\n", "-m", "first")
    commit("h", "x\n", "-m", "second")
    commit("g", "b\n", f"--fixup={first}")
    rehearsal, _ = fold(rewords=[(first, "renamed\n")])
    assert same_tree(git, rehearsal.tip)
    assert subjects(git, rehearsal) == ["renamed", "second"]
