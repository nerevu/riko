"""
Smoke-tests show_def.py.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_show_def.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import show_def

SOURCE = '''
import functools


@functools.cache
async def fetch(url):
    """Fetches a URL."""

    return url


def other():
    return 1
'''


def test_prints_a_named_function_from_its_decorator_without_its_docstring(tmp_path):
    path = tmp_path / "mod.py"
    path.write_text(SOURCE, encoding="utf-8")
    lines = list(show_def.gen_definitions(path, "fetch"))
    assert lines == [
        f"=== {path}:6 fetch",
        "@functools.cache",
        "async def fetch(url):",
        "    return url",
    ]
