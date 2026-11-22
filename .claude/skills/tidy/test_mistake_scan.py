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
    pytest.param(
        "def f(item, field, rule):\n    value = item.get(field)\n"
        "    return bool(value) if rule.get('include') else not value\n",
        "RM102",
        id="bool-value",
    ),
    pytest.param(
        "SWITCH = {'contains': lambda x, y: x and y.lower() in x.lower()}\n",
        "RM101",
        id="lambda-and-guard",
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
        "def f(value):\n    cast('SyncClosable', value).close()\n",
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
    pytest.param(
        "def f(s, m):\n    i = s.find(m) if m else 0\n    return s[i:]\n",
        "RM502",
        id="find-slice-ifexp",
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
        "class Tee:\n    def close(self):\n        pass\n\n"
        "class AsyncTee:\n    async def close(self):\n        pass\n",
        "RM802",
        id="twin-colors",
    ),
    pytest.param(
        "def f(x):\n    if x is None:\n        return 0\n    return x\n",
        "RM901",
        id="early-return",
    ),
    pytest.param(
        "def call(wrapper, conf, options, item=None, context=None, **extra):\n"
        "    pass\n\n"
        "def build(wrapper, conf, options):\n"
        "    return partial(call, wrapper, conf, options)\n",
        "RM1001",
        id="partial-kwarg-shadow",
    ),
    pytest.param(
        "def f(caster, content, default):\n    try:\n"
        "        value = caster(content)\n"
        "    except (TypeError, InvalidOperation, ValueError):\n"
        "        value = default\n    return value\n",
        "RM1101",
        id="cast-overflow",
    ),
    pytest.param(
        "def load(source, defaults):\n"
        "    return _env_int(source, 'RIKO_CONCURRENCY_LIMIT', defaults.limit)\n",
        "RM1102",
        id="env-int-unbounded",
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
    pytest.param(
        "class Tee:\n    def close(self):\n        pass\n\n"
        "    def __call__(self):\n        pass\n\n"
        "class AsyncTee:\n    async def aclose(self):\n        pass\n\n"
        "    async def __call__(self):\n        pass\n\n"
        "class AsyncSub(Sub):\n    async def close(self):\n        pass\n\n"
        "class Sub:\n    def close(self):\n        pass\n",
        id="prefixed-twin",
    ),
    pytest.param(
        "def f(limit, other):\n    return limit and other\n", id="and-no-reuse"
    ),
    pytest.param(
        "def call(wrapper, conf, options, /, item=None, **extra):\n    pass\n\n"
        "def build(wrapper, conf, options):\n"
        "    return partial(call, wrapper, conf, options)\n",
        id="positional-only-partial",
    ),
    pytest.param(
        "def f(caster, content, default):\n    try:\n"
        "        value = caster(content)\n"
        "    except (TypeError, InvalidOperation, ValueError, OverflowError):\n"
        "        value = default\n    return value\n",
        id="cast-overflow-caught",
    ),
    pytest.param(
        "def f(value, default):\n    try:\n"
        "        result = Decimal(str(value))\n"
        "    except (TypeError, InvalidOperation, ValueError):\n"
        "        result = default\n    return result\n",
        id="decimal-only-cast",
    ),
    pytest.param(
        "def cast_arg(value):\n    return value\n\n"
        "def f(value, default):\n    try:\n"
        "        result = cast_arg(value)\n"
        "    except (TypeError, InvalidOperation, ValueError):\n"
        "        result = default\n    return result\n",
        id="named-function-cast",
    ),
    pytest.param(
        "def require(cls, /, value, **_):\n    pass\n\n"
        "require_str = partial(require, str)\n",
        id="module-function-cls",
    ),
    pytest.param(
        "def load(source, defaults):\n    return _env_int(\n"
        "        source, 'RIKO_CONCURRENCY_LIMIT', defaults.limit, minimum=1\n    )\n",
        id="env-int-bounded",
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


def test_class_history_source_is_what_rewrap_builds():
    source = Path(mistake_scan.__file__).read_text()
    assert mistake_scan.build_class_history_source() in source


def test_class_table_lists_every_class_with_rules_or_probe(capsys):
    assert mistake_scan.main(["--classes"]) == 0
    out = capsys.readouterr().out
    assert out.count("\n## ") + out.startswith("## ") == len(mistake_scan.CLASS_HISTORY)
    assert "## kwarg-shadow: RM1001; fixed " in out
    assert "## races: probe-only; fixed " in out


@pytest.mark.parametrize(
    ("cited", "expected"),
    [
        pytest.param(("abc12345",), 0, id="all-cited"),
        pytest.param((), 1, id="one-uncited"),
    ],
)
def test_unclassified_lists_fixes_no_class_cites(monkeypatch, capsys, cited, expected):
    def fake_git(*args: str) -> str:
        replies = {
            "describe": "v1.0.0\n",
            "log": "abc123456 [FIX] Cited fix\ndef987654 [FIX] Typo fix\n",
        }
        return replies[args[0]]

    history = {"close": mistake_scan.BugClass(" ".join(cited), "", "")}
    monkeypatch.setattr(mistake_scan, "git", fake_git)
    monkeypatch.setattr(mistake_scan, "CLASS_HISTORY", history)
    monkeypatch.setattr(mistake_scan, "NON_BEHAVIORAL", ("def98765",))
    assert mistake_scan.main(["--unclassified"]) == expected
    out = capsys.readouterr().out
    assert out == ("" if cited else "abc123456 [FIX] Cited fix\n")


@pytest.mark.parametrize(
    ("refs", "expected", "code"),
    [
        pytest.param("aaaa1111 (11-17 a)", "bbbb2222 (11-17 a)", 0, id="rewritten"),
        pytest.param(
            "uncommitted (11-19 `fmt` alias)",
            "cccc3333 (11-19 `fmt` alias)",
            0,
            id="fix",
        ),
        pytest.param(
            "uncommitted (11-19 `fmt_name` alias)",
            "uncommitted (11-19 `fmt_name` alias)",
            1,
            id="no-match",
        ),
        pytest.param(
            "uncommitted (11-18 `fmt` alias)",
            "uncommitted (11-18 `fmt` alias)",
            1,
            id="other-day",
        ),
    ],
)
def test_remap_rewrites_stale_and_uncommitted_refs(
    tmp_path, monkeypatch, capsys, refs, expected, code
):
    def fake_git(*args: str, check: bool = True) -> str:
        new, fix = f"{'bbbb2222':0<40}", f"{'cccc3333':0<40}"
        replies = {
            "rev-list": f"{new}\n{fix}\n",
            "-1": "[FIX] Old\n",
            "merge-base": "dddd4444\n",
            "--format=%H %s": f"{new} [FIX] Old\n{fix} [FIX] New\n",
            "describe": "v1.0.0\n",
            "--format=%h %s": "cccc3333 [FIX] New\n",
            "--format=%ad": "11-19\n+    fmt = None\n",
        }
        return replies.get(args[1], replies.get(args[0], ""))

    path = tmp_path / "scan.py"
    path.write_text('NON_BEHAVIORAL = (\n    "aaaa1111",\n)\nCLASS_HISTORY = {\n}\n')
    history = {"close": mistake_scan.BugClass(refs, "p", "s")}
    monkeypatch.setattr(mistake_scan, "git", fake_git)
    monkeypatch.setattr(mistake_scan, "CLASS_HISTORY", history)
    monkeypatch.setattr(mistake_scan, "NON_BEHAVIORAL", ("aaaa1111",))
    assert mistake_scan.remap_class_history(path) == code
    source = path.read_text()
    assert f'BugClass("{expected}", "p", "s")' in source
    assert '    "bbbb2222",\n)' in source
    assert ("uncommitted" in capsys.readouterr().out) == bool(code)
