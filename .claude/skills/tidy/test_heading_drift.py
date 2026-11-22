"""
Smoke-tests heading_drift.py.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_heading_drift.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import heading_drift


def test_help_prints_usage_instead_of_diffing(capsys):
    with pytest.raises(SystemExit, match="0"):
        heading_drift.main(["--help"])

    assert "BASE|PATH" in capsys.readouterr().out
