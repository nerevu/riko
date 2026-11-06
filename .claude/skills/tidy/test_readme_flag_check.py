"""
Smoke-tests readme_flag_check.py on a throwaway readme and repo.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_readme_flag_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import readme_flag_check


@pytest.mark.parametrize(
    ("readme", "expected", "code"),
    [
        pytest.param("run with --verbose\n", "no missing flags", 0, id="defined"),
        pytest.param("run with --quiet\n", "--quiet", 1, id="flag"),
        pytest.param("Invoke -TenantId x\n", "-TenantId", 1, id="param"),
        pytest.param("run with --vendored\n", "--vendored", 1, id="skipped-dir"),
    ],
)
def test_reports_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    readme: str,
    expected: str,
    code: int,
) -> None:
    repo = tmp_path / "repo"
    (repo / "node_modules").mkdir(parents=True)
    (repo / "cli.py").write_text('parser.add_argument("--verbose")\n')
    (repo / "notes.txt").write_text("--quiet\n")
    (repo / "node_modules" / "dep.js").write_text("--vendored\n")
    (tmp_path / "README.md").write_text(readme)
    argv = ["readme_flag_check.py", str(tmp_path / "README.md"), str(repo)]
    monkeypatch.setattr(sys, "argv", argv)
    assert readme_flag_check.main() == code
    assert capsys.readouterr().out == f"{expected}\n"
