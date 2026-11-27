"""
Smoke-tests repoint_hashes.py on a throwaway repo whose history was rewritten.

Run after editing repoint_hashes.py:

    uv run --active pytest .claude/skills/wrapup/test_repoint_hashes.py --no-cov
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import repoint_hashes

DATE = "2001-01-01T00:00:00"


@pytest.fixture
def git(tmp_path, monkeypatch):
    def run(*args, date=None):
        config = ("-c", "user.name=t", "-c", "user.email=t@t")
        cmd = ("git", *config, "-c", "core.hooksPath=/dev/null", *args)
        env = {**os.environ, "GIT_COMMITTER_DATE": date} if date else None
        return subprocess.run(
            cmd, cwd=tmp_path, check=True, capture_output=True, text=True, env=env
        ).stdout.strip()

    monkeypatch.chdir(tmp_path)
    run("init", "-q")
    (tmp_path / "a.txt").write_text("a\n")
    run("add", "-A")
    run("commit", "-qm", "init")
    return run


def commit(git, tmp_path, name, text, subject):
    (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / name).write_text(text)
    git("add", "-A")
    git("commit", "-qm", subject)
    return git("rev-parse", "HEAD")


def squash(git, parent, *steps):
    """Commits each ``(sha, message)`` tree on ``parent``; HEAD moves to the last."""
    for sha, message in steps:
        tree = git("rev-parse", f"{sha}^{{tree}}")
        parent = git("commit-tree", tree, "-p", parent, "-m", message, date=DATE)

    git("update-ref", "HEAD", parent)
    return parent


def rewrite(git, *shas):
    """Re-creates each commit on the rewritten line so the old ones go unreachable."""
    steps = [(sha, git("log", "-1", "--format=%s", sha)) for sha in shas]
    return squash(git, f"{shas[0]}^", *steps)


def test_repoints_a_rewritten_citation_at_its_cited_length(git, tmp_path, capsys):
    old = commit(git, tmp_path, "b.txt", "b\n", "Add b")
    doc = tmp_path / "docs" / "notes.md"
    cite = commit(git, tmp_path, "docs/notes.md", f"see {old[:9]}\n", "Cite b")
    rewrite(git, old, cite)
    new = git("rev-parse", "HEAD~1")

    assert repoint_hashes.main(["--paths"]) == 0
    assert doc.read_text() == f"see {new[:9]}\n"
    out = capsys.readouterr().out
    assert f"docs/notes.md:1 {old[:9]} → {new[:9]} (subject)" in out


def test_leaves_and_reports_an_ambiguous_or_dropped_citation(git, tmp_path, capsys):
    old = commit(git, tmp_path, "b.txt", "b\n", "Add b")
    dropped = commit(git, tmp_path, "c.txt", "c\n", "Add c")
    twin = commit(git, tmp_path, "b.txt", "b2\n", "Add b")
    text = f"{old[:8]} and {dropped[:8]}\n"
    cite = commit(git, tmp_path, "docs/notes.md", text, "Cite")
    rewrite(git, old, twin, cite)

    assert repoint_hashes.main(["--paths"]) == 1
    assert (tmp_path / "docs" / "notes.md").read_text() == text
    out = capsys.readouterr().out
    assert f"{old[:8]}: no fallback resolves it" in out
    assert f"{dropped[:8]}: no fallback resolves it" in out


def test_dry_run_writes_nothing(git, tmp_path, capsys):
    old = commit(git, tmp_path, "b.txt", "b\n", "Add b")
    cite = commit(git, tmp_path, "docs/notes.md", f"see {old[:7]}\n", "Cite b")
    rewrite(git, old, cite)

    assert repoint_hashes.main(["--dry-run", "--paths"]) == 0
    assert (tmp_path / "docs" / "notes.md").read_text() == f"see {old[:7]}\n"
    assert f"{old[:7]} → " in capsys.readouterr().out


@pytest.mark.parametrize("by_sha", [False, True], ids=["subject", "sha"])
def test_repoints_a_squashed_fixup_to_its_targets_successor(
    git, tmp_path, capsys, by_sha
):
    target = commit(git, tmp_path, "b.txt", "b\n", "Add b")
    named = target if by_sha else "Add b"
    fixup = commit(git, tmp_path, "b.txt", "b2\n", f"fixup! {named}")
    cite = commit(git, tmp_path, "docs/notes.md", f"see {fixup[:8]}\n", "Cite")
    squashed = squash(git, f"{target}^", (fixup, "Add b"))
    squash(git, squashed, (cite, "Cite"))

    assert repoint_hashes.main(["--paths"]) == 0
    assert (tmp_path / "docs" / "notes.md").read_text() == f"see {squashed[:8]}\n"
    assert f"{fixup[:8]} → {squashed[:8]} (fixup)" in capsys.readouterr().out


def test_repoints_a_dropped_duplicate_to_its_subject_in_history(git, tmp_path, capsys):
    kept = commit(git, tmp_path, "b.txt", "b\n", "Add b")
    dropped = commit(git, tmp_path, "c.txt", "c\n", "Add b")
    cite = commit(git, tmp_path, "docs/notes.md", f"see {dropped[:8]}\n", "Cite")
    squash(git, kept, (cite, "Cite"))

    assert repoint_hashes.main(["--paths"]) == 0
    assert (tmp_path / "docs" / "notes.md").read_text() == f"see {kept[:8]}\n"
    assert f"{dropped[:8]} → {kept[:8]} (history)" in capsys.readouterr().out


def test_repoints_extra_paths_but_skips_archives(git, tmp_path):
    old = commit(git, tmp_path, "b.txt", "b\n", "Add b")
    archive = tmp_path / "_docs" / "archive" / "old.md"
    cite = commit(git, tmp_path, "_docs/archive/old.md", f"see {old[:8]}\n", "Cite")
    rewrite(git, old, cite)
    new = git("rev-parse", "HEAD~1")
    memory = tmp_path.parent / f"{tmp_path.name}-memory"
    archived = memory / "memory-archive" / "old.md"
    archived.parent.mkdir(parents=True)
    (memory / "note.md").write_text(f"see {old[:8]}\n")
    archived.write_text(f"see {old[:8]}\n")

    assert repoint_hashes.main(["--paths", str(memory)]) == 0
    assert (memory / "note.md").read_text() == f"see {new[:8]}\n"
    assert archived.read_text() == f"see {old[:8]}\n"
    assert archive.read_text() == f"see {old[:8]}\n"


def test_reports_but_never_returns_the_remap_exit(git, tmp_path, capsys):
    script = tmp_path / repoint_hashes.REMAP_SCRIPT
    script.parent.mkdir(parents=True)
    script.write_text("import sys\nsys.exit(1)\n")

    assert repoint_hashes.main(["--paths"]) == 0
    assert "mistake_scan.py --remap exited 1" in capsys.readouterr().out


def test_repoints_an_amend_to_the_commit_with_its_amended_subject(
    git, tmp_path, capsys
):
    target = commit(git, tmp_path, "b.txt", "b\n", "[CHANGE] Add b")
    amend = commit(
        git, tmp_path, "b.txt", "b2\n", "amend! [CHANGE] Add b\n\n[NEW] Add b"
    )
    cite = commit(git, tmp_path, "docs/notes.md", f"see {amend[:8]}\n", "Cite")
    amended = squash(git, f"{target}^", (amend, "[NEW] Add b"))
    squash(git, amended, (cite, "Cite"))

    assert repoint_hashes.main(["--paths"]) == 0
    assert (tmp_path / "docs" / "notes.md").read_text() == f"see {amended[:8]}\n"
    assert f"{amend[:8]} → {amended[:8]} (amend)" in capsys.readouterr().out


def test_repoints_a_reworded_commit_by_the_lines_it_added(git, tmp_path, capsys):
    text = "first line long enough to be specific\nsecond line also long enough here\n"
    old = commit(git, tmp_path, "b.txt", text, "Add b")
    cite = commit(git, tmp_path, "docs/notes.md", f"see {old[:8]}\n", "Cite")
    reworded = squash(git, f"{old}^", (old, "Write b"))
    squash(git, reworded, (cite, "Cite"))

    assert repoint_hashes.main(["--paths"]) == 0
    assert (tmp_path / "docs" / "notes.md").read_text() == f"see {reworded[:8]}\n"
    assert f"{old[:8]} → {reworded[:8]} (content)" in capsys.readouterr().out


def test_content_prefers_code_lines_over_reworded_prose(git, tmp_path, capsys):
    prose = "a changelog sentence that a later fold rewords\n"
    docstring = "    a docstring sentence that a later fold rewords too\n"
    head = 'def f():\n    """\n'
    tail = '    """\n\n\ndef build_the_long_function_name():\n'
    commit(git, tmp_path, "b.py", f'{head}    short\n    """\n', "Add b")
    commit(git, tmp_path, "CHANGES.rst", prose, "Add changelog")
    commit(git, tmp_path, "c.py", f'"""\n{docstring}"""\n', "Add docstring")
    (tmp_path / "CHANGES.rst").write_text("")
    (tmp_path / "c.py").write_text("")
    git("commit", "-qam", "Drop prose")
    (tmp_path / "CHANGES.rst").write_text(prose)
    text = f"{head}{docstring}{tail}    return the_long_value_name\n"
    old = commit(git, tmp_path, "b.py", text, "Grow b")
    cite = commit(git, tmp_path, "docs/notes.md", f"see {old[:8]}\n", "Cite")
    reworded = squash(git, f"{old}^", (old, "Write b"))
    squash(git, reworded, (cite, "Cite"))

    assert repoint_hashes.main(["--paths"]) == 0
    assert f"{old[:8]} → {reworded[:8]} (content)" in capsys.readouterr().out


def test_content_skips_import_lines(git, tmp_path, capsys):
    imports = "from collections.abc import AsyncIterator, Callable, Iterator\n"
    code = "def build_the_long_function_name():\n    return the_long_value_name\n"
    commit(git, tmp_path, "c.py", imports, "Add c")
    (tmp_path / "c.py").write_text("")
    git("commit", "-qam", "Empty c")
    old = commit(git, tmp_path, "b.py", f"{imports}\n\n{code}", "Add b")
    cite = commit(git, tmp_path, "docs/notes.md", f"see {old[:8]}\n", "Cite")
    reworded = squash(git, f"{old}^", (old, "Write b"))
    squash(git, reworded, (cite, "Cite"))

    assert repoint_hashes.main(["--paths"]) == 0
    assert f"{old[:8]} → {reworded[:8]} (content)" in capsys.readouterr().out


def test_keeps_the_old_side_of_a_mapping_record(git, tmp_path, capsys):
    old = commit(git, tmp_path, "b.txt", "b\n", "Add b")
    gone = commit(git, tmp_path, "c.txt", "c\n", "Add c")
    text = f"(ruling for {old[:8]} → {old[:8]})\n`{gone[:8]}` -> {old[:8]}\n"
    cite = commit(git, tmp_path, "docs/notes.md", text, "Cite")
    squash(git, f"{old}^", (old, "Add b"), (cite, "Cite"))
    new = git("rev-parse", "HEAD~1")

    assert repoint_hashes.main(["--paths"]) == 0
    notes = (tmp_path / "docs" / "notes.md").read_text()
    assert notes == f"(ruling for {old[:8]} → {new[:8]})\n`{gone[:8]}` -> {new[:8]}\n"
    out = capsys.readouterr().out
    assert f"docs/notes.md:1 {old[:8]}: kept (mapping record)" in out
    assert f"docs/notes.md:2 {gone[:8]}: kept (mapping record)" in out
