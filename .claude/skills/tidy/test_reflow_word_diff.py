"""
Smoke-tests reflow_word_diff.py on a throwaway git repository.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_reflow_word_diff.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import reflow_word_diff

BEFORE = "# Title\n\nOne two three four five six seven eight.\n\n* item\n"
REFLOWED = "# Title\n\nOne two three four\nfive six seven eight.\n\n- item\n"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    def git(*args: str) -> None:
        subprocess.run(
            [reflow_word_diff.GIT, *args], cwd=tmp_path, check=True, capture_output=True
        )

    git("init", "-q")
    (tmp_path / "doc.md").write_text(BEFORE)
    git("add", "doc.md")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "doc")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["reflow_word_diff.py", "HEAD"])
    return tmp_path


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(REFLOWED, "", id="reflow-only"),
        pytest.param(REFLOWED.replace("six", "SIX"), "-'six' +'SIX'", id="wording"),
    ],
)
def test_reports_only_wording_changes(repo, capsys, text, expected):
    (repo / "doc.md").write_text(text)
    assert reflow_word_diff.main() == 0
    out = capsys.readouterr().out
    assert (expected in out) if expected else out == ""
