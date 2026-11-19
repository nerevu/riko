"""
Smoke-tests gates.py on a throwaway repository.

Run after editing gates.py:

    uv run --active pytest .claude/skills/land/test_gates.py
"""

from __future__ import annotations

import fcntl
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import gates
import require_agents

RUFF_GATES = frozenset({"tidy", "lint", "prettify"})
TYPE_GATES = frozenset({"check-types", "verify-types"})
ALL_GATES = RUFF_GATES | TYPE_GATES | {"test", "uncovered", "codegen"}
TREE_FILES = (
    ".claude/skills/SKILL.md",
    ".claude/skills/helper.py",
    "_docs/x.md",
    "CLAUDE.md",
    ".github/ci.yml",
    "docs/x.rst",
    "pyproject.toml",
    "typings/x.pyi",
)


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


def test_tree_id_removes_its_temporary_index(repo, tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    gates.get_tree_id()
    assert list(scratch.iterdir()) == []


@pytest.mark.parametrize(
    ("edited", "changed"),
    [
        pytest.param(".claude/skills/SKILL.md", RUFF_GATES, id="skill-prose"),
        pytest.param(".claude/skills/helper.py", RUFF_GATES, id="skill-script"),
        pytest.param("_docs/x.md", {*RUFF_GATES, "codegen"}, id="internal-docs"),
        pytest.param("CLAUDE.md", {*RUFF_GATES, "codegen"}, id="root-markdown"),
        pytest.param(".github/ci.yml", {*RUFF_GATES, "codegen"}, id="workflows"),
        pytest.param("docs/x.rst", ALL_GATES - TYPE_GATES, id="user-docs"),
        pytest.param("a.py", ALL_GATES, id="source"),
        pytest.param("pyproject.toml", ALL_GATES, id="pyproject"),
        pytest.param("typings/x.pyi", ALL_GATES, id="stub"),
    ],
)
def test_tree_id_leaves_out_what_each_gate_never_reads(repo, tmp_path, edited, changed):
    for name in TREE_FILES:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("one\n")

    repo("add", "-f", "-A")
    repo("commit", "-qm", "files")
    ids = {gate: gates.get_tree_id(gate) for gate in ALL_GATES}
    (tmp_path / edited).write_text("two\n")

    assert {
        gate for gate in ALL_GATES if gates.get_tree_id(gate) != ids[gate]
    } == changed


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
def test_scope_leads_prints_each_lead_after_the_scope(tmp_path, capsys):
    path = gates.get_state_dir() / "gate-markers.json"
    stub = tmp_path / ".claude" / "lead.py"
    stub.parent.mkdir()
    stub.write_text("import sys\nprint(' '.join(sys.argv[1:]))\n")
    prefixes = {name: [sys.executable, str(stub)] for name in gates.LEAD_NAMES}
    (tmp_path / "a.py").write_text("a = 2\n")
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    (tmp_path / "tests" / "unit" / "test_a.py").write_text("x = 1\n")

    assert gates.scope(path, "tidy", leads=prefixes) == 1
    out = capsys.readouterr().out
    leads = out.split("\n--- lint\n", 1)[1]
    assert "+a = 2" in out.split("--- lint")[0]
    assert "lint --terms --literals --docstrings --bindings --tests" in leads
    assert "--- neighborhood\n" in leads
    assert "--context 2" in leads.split("--- neighborhood\n")[1]
    assert "--- mistake_scan\n" in leads
    assert "--files tests/unit/test_a.py" in leads.split("--- overlap_scan\n")[1]
    assert "--- heading_drift" not in leads
    assert "+a = 2" in path.with_name("tidy-scope.diff").read_text()


def test_gen_edits_drops_lines_a_hunk_only_moved():
    diff = (
        "--- a/t.py\n+++ b/t.py\n@@ -1,2 +1,3 @@\n-def kept():\n+x = 1\n"
        " context\n+def kept():\n"
    )
    assert list(gates.gen_edits(diff)) == ["t.py:1: x = 1"]


@pytest.mark.usefixtures("repo")
def test_scope_edits_only_prints_the_new_lines(tmp_path, capsys):
    path = gates.get_state_dir() / "gate-markers.json"
    (tmp_path / "a.py").write_text("a = 2\n")
    capsys.readouterr()

    assert gates.scope(path, "tidy", edits_only=True) == 1
    assert "--- edits" in (out := capsys.readouterr().out)
    assert "a.py:1: a = 2" in out


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


@pytest.mark.usefixtures("repo")
def test_all_stops_at_the_first_failing_gate_and_skips_recorded_ones(tmp_path, capsys):
    path = gates.get_state_dir() / "gate-markers.json"
    fake = tmp_path / ".claude" / "manage.py"
    fake.parent.mkdir()
    fake.write_text(
        "import sys\nsys.exit(3 if sys.argv[1:3] == ['lint', '--all'] else 0)\n"
    )
    argv = ["all", "--manage", shlex.join([sys.executable, str(fake)])]

    assert gates.main(argv) == 3
    out = capsys.readouterr().out
    assert gates.check(path, "prettify") == 0
    assert gates.check(path, "lint") == 1
    summary = out.split("--- gates\n")[1].splitlines()
    assert summary == [
        "pass prettify",
        "fail (3) lint",
        "pass check-types",
        "pass verify-types",
        "not run test",
    ]
    capsys.readouterr()
    assert gates.main(argv) == 3
    assert "skip prettify" in capsys.readouterr().out.split("--- gates\n")[1]


@pytest.mark.usefixtures("repo")
def test_all_stops_at_a_pass_the_tree_change_left_unrecorded(tmp_path, capsys):
    path = gates.get_state_dir() / "gate-markers.json"
    fake = tmp_path / ".claude" / "manage.py"
    fake.parent.mkdir()
    fake.write_text(
        "import pathlib, sys\n"
        "if sys.argv[1:3] == ['lint', '--all']:\n"
        "    pathlib.Path('touched.txt').write_text('x')\n"
    )
    argv = ["all", "--manage", shlex.join([sys.executable, str(fake)])]

    assert gates.main(argv) == gates.UNRECORDED
    summary = capsys.readouterr().out.split("--- gates\n")[1].splitlines()
    assert summary == [
        "pass prettify",
        "pass (unrecorded) lint",
        "pass check-types",
        "pass verify-types",
        "not run test",
    ]
    assert gates.check(path, "lint") == 1


@pytest.mark.usefixtures("repo")
def test_all_skips_the_suite_after_a_type_failure_but_reports_lint(tmp_path, capsys):
    fake = tmp_path / ".claude" / "manage.py"
    fake.parent.mkdir()
    fake.write_text(
        "import sys\nsys.exit(4 if sys.argv[1:3] == ['lint', '--check-types'] else 0)\n"
    )
    argv = ["all", "--manage", shlex.join([sys.executable, str(fake)])]

    assert gates.main(argv) == 4
    summary = capsys.readouterr().out.split("--- gates\n")[1].splitlines()
    assert summary == [
        "pass prettify",
        "pass lint",
        "fail (4) check-types",
        "pass verify-types",
        "not run test",
    ]


@pytest.mark.usefixtures("repo")
def test_all_read_only_runs_only_the_side_by_side_gates(tmp_path, capsys):
    fake = tmp_path / ".claude" / "manage.py"
    fake.parent.mkdir()
    fake.write_text("")
    argv = ["all", "--read-only", "--manage", shlex.join([sys.executable, str(fake)])]

    assert gates.main(argv) == 0
    assert capsys.readouterr().out.split("--- gates\n")[1].splitlines() == [
        "not run prettify",
        "pass lint",
        "pass check-types",
        "pass verify-types",
        "not run test",
    ]


def test_all_read_only_rejects_codegen():
    with pytest.raises(SystemExit, match="2"):
        gates.main(["all", "--read-only", "--codegen"])


@pytest.mark.parametrize(
    ("setup", "carried"),
    [
        pytest.param([["record", "tidy"]], True, id="marked"),
        pytest.param([], False, id="unmarked"),
    ],
)
@pytest.mark.usefixtures("repo")
def test_prettify_carries_tidy_only_from_a_marked_tree(
    tmp_path, capsys, setup, carried
):
    path = gates.get_state_dir() / "gate-markers.json"
    command = ["sh", "-c", f"echo 'a = 3' > {tmp_path / 'a.py'}"]

    for argv in setup:
        gates.main(argv)

    capsys.readouterr()
    assert gates.main(["run", "prettify", "--mutates", "--", *command]) == 0
    assert gates.check(path, "tidy") == (0 if carried else 1)
    assert "not recorded" not in capsys.readouterr().out


@pytest.mark.usefixtures("repo")
def test_skipped_prettify_leaves_tidy_marker_alone(tmp_path):
    path = gates.get_state_dir() / "gate-markers.json"
    gates.main(["record", "tidy"])
    tidied = gates.load_markers(path)["tidy"]
    (tmp_path / "a.py").write_text("a = 4\n")
    gates.main(["record", "prettify"])
    command = ["sh", "-c", f"echo 'a = 3' > {tmp_path / 'a.py'}"]

    assert gates.main(["run", "prettify", "--mutates", "--", *command]) == 0
    assert gates.load_markers(path)["tidy"] == tidied
    assert (tmp_path / "a.py").read_text() == "a = 4\n"


@pytest.mark.usefixtures("repo")
def test_all_prints_each_side_by_side_gate_whole_under_its_header(tmp_path, capsys):
    fake = tmp_path / ".claude" / "manage.py"
    fake.parent.mkdir()
    fake.write_text(
        "import sys, time\n"
        "name = sys.argv[-1]\n"
        "for n in range(3):\n"
        "    print(f'{name} line {n}', flush=True)\n"
        "    time.sleep(0.05)\n"
    )
    argv = ["all", "--manage", shlex.join([sys.executable, str(fake)])]

    assert gates.main(argv) == 0
    out = capsys.readouterr().out.split("--- gates\n")[0]
    sections = dict(
        section.split("\n", 1) for section in out.split("--- ")[1:] if section
    )
    assert set(sections) == {"lint", "check-types", "verify-types"}

    for gate, flag in [("lint", "--all"), ("check-types", "--check-types")]:
        lines = sections[gate].splitlines()
        assert lines[:3] == [f"{flag} line {n}" for n in range(3)]
        assert lines[3].startswith(f"recorded {gate} on tree ")


@pytest.mark.parametrize(
    ("ceiling", "recorded"),
    [
        pytest.param(
            "uncovered = 319\nuncovered-lowered = 2026-11-18\n", True, id="lowered"
        ),
        pytest.param(
            "uncovered = 321\nuncovered-lowered = 2026-11-18\n", False, id="raised"
        ),
        pytest.param("uncovered = 320\ntimeout = 30\n", False, id="other-key"),
        pytest.param("uncovered = 319\nname = 'riko2'\n", False, id="other-line"),
    ],
)
@pytest.mark.usefixtures("repo")
def test_run_records_a_ratchet_lowering_its_ceiling(repo, tmp_path, ceiling, recorded):
    path = gates.get_state_dir() / "gate-markers.json"
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.riko.coverage]\nuncovered = 320\n")
    repo("add", "pyproject.toml")
    repo("commit", "-qm", "pyproject")
    script = "import pathlib, sys\npathlib.Path(sys.argv[1]).write_text(sys.argv[2])\n"
    text = f"[tool.riko.coverage]\n{ceiling}"
    command = [sys.executable, "-c", script, str(pyproject), text]

    assert gates.run(path, "test", command, mutates=False, lock=False) == 0
    assert gates.check(path, "test") == (0 if recorded else 1)


@pytest.mark.usefixtures("repo")
def test_ratchet_change_rejects_a_second_file(tmp_path):
    before = gates.get_tree_id("test")
    (tmp_path / "pyproject.toml").write_text("uncovered = 319\n")
    (tmp_path / "a.py").write_text("a = 2\n")

    assert not gates.is_ratchet_change(before, gates.get_tree_id("test"))


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        pytest.param({}, ["auditor.md is", "implementer.md is"], id="none"),
        pytest.param(
            {"auditor": "Bash, Read", "implementer": "Bash, Read, Edit"},
            ["implementer.md: grant the tools Write"],
            id="short-grant",
        ),
        pytest.param(
            {"auditor": "Bash, Read", "implementer": "Bash, Read, Edit, Write"},
            [],
            id="complete",
        ),
    ],
)
def test_require_agents(tmp_path, files, expected):
    for name, tools in files.items():
        (tmp_path / f"{name}.md").write_text(f"---\ntools: {tools}\n---\n")

    problems = require_agents.get_problems(tmp_path)
    assert len(problems) == len(expected)
    assert all(want in got for want, got in zip(expected, problems, strict=True))
