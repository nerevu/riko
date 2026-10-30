"""
Smoke-tests neighborhood.py on a throwaway repository.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_neighborhood.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import neighborhood

BEFORE = "LIMIT = 1\n\n\ndef fetch(url):\n    return url\n\n\nclass Old:\n    pass\n"
AFTER = (
    "class Gone:\n    pass\n\n\nLIMIT = 2\n\n\ndef fetch(url, timeout):\n"
    "    return url\n\n\nclass New:\n    pass\n"
)
CALLER = "from a import Old, fetch\n\nfetch(1)\nOld()\n\n\nclass Gone:\n    pass\n"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(
            [neighborhood.GIT, *args], cwd=tmp_path, check=True, capture_output=True
        )

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / "riko").mkdir()
    (tmp_path / "riko" / "a.py").write_text(BEFORE)
    git("add", "-A")
    git("commit", "-qm", "init")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "use.rst").write_text("Call ``fetch`` after ``Old``.\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(CALLER)
    git("add", "-A")
    git("commit", "-qm", "caller")
    (tmp_path / "riko" / "a.py").write_text(AFTER)
    (tmp_path / "tests" / "test_a.py").write_text(
        CALLER.split("\n\n\nclass Gone", maxsplit=1)[0] + "\n"
    )
    monkeypatch.chdir(tmp_path)
    return git


@pytest.mark.usefixtures("repo")
def test_report_lists_surviving_references_of_removed_and_resigned_names(capsys):
    assert (
        neighborhood.main(["--base", "HEAD", "--roots", "riko", "tests", "docs"]) == 0
    )
    out = capsys.readouterr().out
    change = neighborhood.parse_diff(neighborhood.load_diff("HEAD", None))["riko/a.py"]

    assert change.gone == ["Old"]
    assert change.resigned == ["fetch"]
    assert change.new == ["Gone", "New"]
    assert "removed Old (3 references)" in out
    assert "re-signed fetch (3 references)" in out
    assert "tests/test_a.py:4:Old()" in out
    assert "docs/use.rst:1:" in out
    assert "riko/a.py:4:def fetch" not in out
    assert "LIMIT" not in out
    assert "added Gone, New" in out
    assert "moved Gone -> riko/a.py" in out
    assert "removed Gone" not in out
