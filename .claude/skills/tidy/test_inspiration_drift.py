"""
Smoke-tests inspiration_drift.py on throwaway snapshots and sources.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_inspiration_drift.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import inspiration_drift

BODY = b"# proj\n\nText.\n"


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    snapshots = tmp_path / "inspiration"
    snapshots.mkdir()
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "README.md").write_bytes(BODY)
    monkeypatch.setattr(inspiration_drift, "_INSPIRATION", snapshots)
    monkeypatch.setattr(sys, "argv", ["inspiration_drift.py"])
    return snapshots


@pytest.mark.parametrize(
    ("name", "content", "expected", "code"),
    [
        pytest.param(
            "proj.md",
            b"---\nsource: ../proj/README.md\n---\n\n" + BODY,
            "same",
            0,
            id="md",
        ),
        pytest.param(
            "proj.rst", b".. source: ../proj/README.md\n\n" + BODY, "same", 0, id="rst"
        ),
        pytest.param(
            "proj.md",
            b"---\nsource: ../proj/README.md\n---\n\n# changed\n",
            "differs (",
            1,
            id="differs",
        ),
        pytest.param(
            "gone.md",
            b"---\nsource: ../gone/README.md\n---\n\n" + BODY,
            "missing source",
            1,
            id="missing",
        ),
        pytest.param("script.py", b"print(1)\n", "no source line", 0, id="no-header"),
    ],
)
def test_reports_status(
    tree: Path,
    capsys: pytest.CaptureFixture[str],
    name: str,
    content: bytes,
    expected: str,
    code: int,
) -> None:
    (tree / name).write_bytes(content)
    assert inspiration_drift.main() == code
    assert f"{name}: {expected}" in capsys.readouterr().out
