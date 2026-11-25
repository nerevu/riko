"""
Smoke-tests move_tests.py on a throwaway repository.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_move_tests.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import move_tests

SOURCE = """\
class TestSource:
    def test_kept(self):
        assert True

    def test_moved(self):
        assert True
"""

DEST = """\
class TestDest:
    def test_existing(self):
        assert True
"""

CITATION = "See `tests/internal/test_source.py::TestSource::test_moved`.\n"


HELPER_SOURCE = """\
import json

TABLE = [1]


def _shared():
    return 1


def _only_moved():
    return json.dumps(TABLE)


class TestSource:
    def test_kept(self):
        assert _shared()

    def test_moved(self):
        assert _only_moved() and _shared()
"""


def _run_move(tmp_path, monkeypatch, source_text, *flags):
    tier = tmp_path / "tests" / "internal"
    tier.mkdir(parents=True)
    source, dest = tier / "test_source.py", tier / "test_dest.py"
    source.write_text(source_text)
    dest.write_text(DEST)
    argv = [
        "move_tests.py",
        "tests/internal/test_dest.py::TestDest",
        "tests/internal/test_source.py::TestSource::test_moved",
        *flags,
    ]
    monkeypatch.setattr(move_tests, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    assert not move_tests.main()
    return source.read_text(), dest.read_text()


def test_move_relocates_a_method_and_repoints_its_citation(tmp_path, monkeypatch):
    (tmp_path / "_docs").mkdir()
    notes = tmp_path / "_docs" / "NOTES.md"
    notes.write_text(CITATION)

    source, dest = _run_move(tmp_path, monkeypatch, SOURCE)

    assert "test_moved" not in source
    assert "test_kept" in source
    assert "def test_moved" in dest
    assert "test_dest.py::TestDest::test_moved" in notes.read_text()


TWIN_NAME = """\


class TestOther:
    def test_moved(self):
        assert True
"""
BARE_RENAMES = [
    pytest.param("", "`test_renamed`", id="bare-lone-name"),
    pytest.param(TWIN_NAME, "`test_moved`", id="bare-name-still-carried"),
]


@pytest.mark.parametrize(("extra", "cited"), BARE_RENAMES)
def test_a_renamed_method_repoints_its_bare_citation(
    tmp_path, monkeypatch, extra, cited
):
    (tmp_path / "_docs").mkdir()
    notes = tmp_path / "_docs" / "NOTES.md"
    notes.write_text("See `test_moved` and `test_moved[row]`.\n")

    _run_move(tmp_path, monkeypatch, SOURCE + extra, "--rename", "test_renamed")

    assert notes.read_text() == f"See {cited} and {cited[:-1]}[row]`.\n"


def test_with_helpers_carries_only_the_moved_methods_helpers(
    tmp_path, monkeypatch, capsys
):
    source, dest = _run_move(tmp_path, monkeypatch, HELPER_SOURCE, "--with-helpers")

    assert "_only_moved" not in source
    assert "TABLE" not in source
    assert "def _shared" in source
    assert "def _shared" not in dest
    assert "import json" in dest
    assert dest.index("TABLE = [1]") < dest.index("def _only_moved")
    assert dest.index("def _only_moved") < dest.index("class TestDest")
    assert "NOT moved: _shared" in capsys.readouterr().out


SPLIT_SOURCE = """\
SHARED = 1
ONLY_A = [
    1,
]


class TestA:
    def test_a(self):
        assert ONLY_A and SHARED


class TestB:
    def test_b(self):
        assert SHARED
"""


def test_plan_split_prints_footprints_and_shared_helpers(tmp_path):
    path = tmp_path / "test_split.py"
    path.write_text(SPLIT_SOURCE)
    assert list(move_tests.gen_split_plan(path)) == [
        f"shared {path}:1 1 lines: TestA, TestB",
        f"TestA {path}:7 class=3 helpers=3",
        f"TestB {path}:12 class=3 helpers=0",
    ]


TWIN_SOURCE = """\
class TestSyncRun:
    def test_refuses(self):
        with pytest.raises(E):
            run()


class TestAsyncRun:
    async def test_refuses(self):
        with pytest.raises(E):
            await arun()

        assert not held

    async def test_runs(self):
        assert await arun()
"""


def test_sort_files_a_twin_of_a_rejection_with_it(tmp_path, monkeypatch, capsys):
    path = tmp_path / "test_twin.py"
    path.write_text(TWIN_SOURCE)
    argv = ["move_tests.py", "--sort", "--dry-run", f"{path}::TestAsyncRun"]
    monkeypatch.setattr(sys, "argv", argv)

    assert not move_tests.main()
    assert capsys.readouterr().out.splitlines()[1:] == [
        "  behavior  test_runs",
        "  rejection test_refuses",
    ]


CHAIN_LOAD = "def _load(value):\n    return value\n\n\n"
CHAIN_BUILD = "def _build(value):\n    return _load(value)\n\n\n"
CHAIN_OTHER = "class TestOther:\n    def test_other(self):\n        assert True\n\n\n"
CHAIN_USER = "class TestX:\n    def test_x(self):\n        assert _build(1)\n"


def test_place_leads_puts_a_helper_above_its_caller_in_place(tmp_path, monkeypatch):
    tier = tmp_path / "tests" / "internal"
    tier.mkdir(parents=True)
    path = tier / "test_chain.py"
    path.write_text(CHAIN_LOAD + CHAIN_OTHER + CHAIN_BUILD + CHAIN_USER)
    monkeypatch.setattr(move_tests, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["move_tests.py", "--place-leads", str(path)])

    assert not move_tests.main()
    assert path.read_text() == CHAIN_OTHER + CHAIN_LOAD + CHAIN_BUILD + CHAIN_USER


RENAME_SOURCE = """\
class TestOld:
    def test_x(self):
        assert True


class TestAfter:
    def test_y(self):
        assert True
"""
RENAME_NOTES = (
    "See `tests/internal/test_source.py::TestOld::test_x`.\nTestOld covers x.\n"
)
RENAMED_CITATION = "See `tests/internal/test_source.py::TestNew::test_x`.\n"
OTHER_OLD = "class TestOld:\n    pass\n"
IN_PLACE_RENAMES = [
    pytest.param(
        "",
        "TestNew covers x.\n",
        "_docs/NOTES.md:2: TestOld -> TestNew",
        id="unique-name-prose-rewritten",
    ),
    pytest.param(
        OTHER_OLD,
        "TestOld covers x.\n",
        "_docs/NOTES.md:2: TestOld (ambiguous, left)",
        id="ambiguous-name-prose-left",
    ),
]


def _run_rename(tmp_path, monkeypatch, other):
    tier = tmp_path / "tests" / "internal"
    tier.mkdir(parents=True)
    source = tier / "test_source.py"
    source.write_text(RENAME_SOURCE)
    (tier / "test_other.py").write_text(other)
    (tmp_path / "_docs").mkdir()
    notes = tmp_path / "_docs" / "NOTES.md"
    notes.write_text(RENAME_NOTES)
    argv = [
        "move_tests.py",
        "tests/internal/test_source.py",
        "tests/internal/test_source.py::TestOld",
        "--rename",
        "TestNew",
    ]
    monkeypatch.setattr(move_tests, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)
    return source, notes


@pytest.mark.parametrize(("other", "prose", "reported"), IN_PLACE_RENAMES)
def test_a_same_file_rename_renames_the_class_in_place(
    tmp_path, monkeypatch, capsys, other, prose, reported
):
    source, notes = _run_rename(tmp_path, monkeypatch, other)

    assert not move_tests.main()
    assert source.read_text() == RENAME_SOURCE.replace("TestOld", "TestNew")
    assert notes.read_text() == RENAMED_CITATION + prose
    assert reported in capsys.readouterr().out.splitlines()


def test_an_in_place_rename_refuses_a_class_name_used_elsewhere(tmp_path, monkeypatch):
    source, notes = _run_rename(tmp_path, monkeypatch, OTHER_OLD.replace("Old", "New"))

    with pytest.raises(SystemExit, match="TestNew already exists"):
        move_tests.main()

    assert source.read_text() == RENAME_SOURCE
    assert notes.read_text() == RENAME_NOTES
