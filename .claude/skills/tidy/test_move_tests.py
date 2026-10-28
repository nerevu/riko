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


def test_move_relocates_a_method_and_repoints_its_citation(tmp_path, monkeypatch):
    tier = tmp_path / "tests" / "internal"
    tier.mkdir(parents=True)
    source, dest = tier / "test_source.py", tier / "test_dest.py"
    source.write_text(SOURCE)
    dest.write_text(DEST)
    (tmp_path / "_docs").mkdir()
    notes = tmp_path / "_docs" / "NOTES.md"
    notes.write_text(CITATION)

    argv = [
        "move_tests.py",
        "tests/internal/test_dest.py::TestDest",
        "tests/internal/test_source.py::TestSource::test_moved",
    ]
    monkeypatch.setattr(move_tests, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    assert not move_tests.main()
    assert "test_moved" not in source.read_text()
    assert "test_kept" in source.read_text()
    assert "def test_moved" in dest.read_text()
    assert "test_dest.py::TestDest::test_moved" in notes.read_text()
