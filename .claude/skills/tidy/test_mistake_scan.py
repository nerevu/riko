"""
Smoke-tests mistake_scan.py on snippets shaped like the bugs its rules were mined from.

Run after editing the tidy scripts:

    uv run --active pytest .claude/skills/tidy/test_mistake_scan.py --no-cov
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import mistake_scan

RULE_CASES = [
    pytest.param("def f(limit):\n    return limit or 10\n", "RM101", id="or-default"),
    pytest.param(
        "def f(newval):\n    if newval:\n        pass\n", "RM102", id="if-value"
    ),
    pytest.param("def f(it):\n    yield next(it)\n", "RM103", id="bare-next"),
    pytest.param("def f(s):\n    return list(set(s))\n", "RM201", id="set-order"),
    pytest.param("def f(a, b):\n    g(*a.difference(b))\n", "RM201", id="set-splat"),
    pytest.param("import json\njson.loads('{}')\n", "RM301", id="json-loads"),
    pytest.param(
        "def f(it):\n    if isinstance(it, Generator):\n        it.close()\n",
        "RM401",
        id="generator-close",
    ),
    pytest.param(
        "def f(cleanup, v):\n    cleanup(v)\n", "RM402", id="dropped-callback"
    ),
    pytest.param(
        "async def f(s):\n    async for x in g(s):\n        yield x\n",
        "RM403",
        id="no-aclosing",
    ),
    pytest.param(
        "def f(value):\n    cast('SyncCloseable', value).close()\n",
        "RM404",
        id="cast-close",
    ),
    pytest.param(
        "def f[T](value: T):\n    value.close()\n", "RM404", id="generic-close"
    ),
    pytest.param("def f(raw):\n    return raw.decode('utf-8')\n", "RM501", id="decode"),
    pytest.param(
        "def f(s, m):\n    i = s.find(m)\n    return s[i:]\n", "RM502", id="find-slice"
    ),
    pytest.param("def f(timeout=0):\n    pass\n", "RM601", id="timeout-zero"),
    pytest.param(
        "@define(frozen=True)\nclass C:\n    modes: frozenset[str]\n",
        "RM701",
        id="frozen-no-converter",
    ),
    pytest.param(
        "def read(url):\n    get(url, timeout=1)\n\n"
        "async def aread(url):\n    await get(url)\n",
        "RM801",
        id="twin-keywords",
    ),
    pytest.param(
        "def f(x):\n    if x is None:\n        return 0\n    return x\n",
        "RM901",
        id="early-return",
    ),
]
CLEAN_CASES = [
    pytest.param("def f(limit):\n    return limit or 0\n", id="empty-default"),
    pytest.param("def f(is_ok):\n    if is_ok:\n        pass\n", id="predicate"),
    pytest.param("def f(it):\n    yield next(it, None)\n", id="next-default"),
    pytest.param(
        "class C:\n    def __hash__(self):\n        return hash(1)\n", id="dunder-hash"
    ),
    pytest.param(
        "def f(it):\n    if isinstance(it, AsyncGenerator):\n        raise E\n"
        "    else:\n        it.close()\n",
        id="type-discriminator",
    ),
    pytest.param(
        "async def f(s):\n    async with aclosing(g(s)) as r:\n"
        "        async for x in r:\n            yield x\n",
        id="aclosing",
    ),
    pytest.param("def f(stream: IO[str]):\n    stream.close()\n", id="typed-close"),
    pytest.param(
        "def f[T](result: T | Awaitable[T]):\n    if iscoroutine(result):\n"
        "        result.close()\n",
        id="narrowed-close",
    ),
    pytest.param(
        "def f(limit):\n    return limit or 10  # mistake-ok: RM101\n", id="suppressed"
    ),
    pytest.param(
        "def f(x):\n    def g():\n        return 1\n\n    return g\n",
        id="nested-return",
    ),
]


def _codes(tmp_path: Path, source: str) -> set[str]:
    path = tmp_path / "mod.py"
    path.write_text(source)
    return {lead.code for lead in mistake_scan.scan_file(path)}


@pytest.mark.parametrize(("source", "code"), RULE_CASES)
def test_each_rule_flags_its_origin_shape(tmp_path, source, code):
    assert code in _codes(tmp_path, source)


@pytest.mark.parametrize("source", CLEAN_CASES)
def test_reviewed_and_safe_shapes_stay_quiet(tmp_path, source):
    assert not _codes(tmp_path, source)


def test_diff_scope_reports_only_added_lines(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mistake_scan, "ROOT", tmp_path)
    (tmp_path / "riko").mkdir()
    (tmp_path / "riko" / "a.py").write_text(
        "def f(limit):\n    return limit or 1\n\n\n"
        "def g(count):\n    return count or 2\n"
    )
    diff_file = tmp_path / "scope.diff"
    diff_file.write_text(
        "diff --git a/riko/a.py b/riko/a.py\n--- a/riko/a.py\n+++ b/riko/a.py\n"
        "@@ -1,6 +1,6 @@\n def f(limit):\n     return limit or 1\n \n \n"
        " def g(count):\n"
        "-    return count\n+    return count or 2\n"
    )
    assert mistake_scan.main(["--diff-file", str(diff_file)]) == 1
    out = capsys.readouterr().out
    assert "riko/a.py:6: RM101" in out
    assert "riko/a.py:2:" not in out
