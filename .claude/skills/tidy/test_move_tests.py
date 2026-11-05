"""
Smoke-tests move_tests.py on a throwaway repository.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_move_tests.py
"""

from __future__ import annotations

import sys
from pathlib import Path

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
