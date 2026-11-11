"""
Fits each test bound to the bound ladder from measured durations.

Usage:
    uv run --active python .claude/skills/tidy/fit_bounds.py DURATIONS_FILE \\
        [DURATIONS_FILE ...] [--files TEST_FILE ...]

Each DURATIONS_FILE is the saved output of a run from the repository root:

    pytest -n auto --no-cov --durations=0 > durations-1.txt

A bound fits when it is the smallest ladder step (1, 2, 3, 5, 8, 10, 15, 20, 30
seconds) that is at least five times the test's worst ``call`` time across all
files, with a floor of 1 second; parametrized rows share their test's worst time,
and a class-level marker takes the worst over the class's tests.

An inner bound (a ``join``/``wait``/``result`` timeout or a ``fail_after`` block)
must stay below the bound that encloses it: the innermost ``fail_after`` or
``move_on_after`` block around it, else the test's ``timeout`` marker, else the
``pyproject.toml`` timeout. Its fit is capped at the largest ladder step under that
cap, and such a line ends ``cap=TEXT``; a capped bound that sits at its cap is
``ok``, since only the enclosing bound can grow.

A test that asserts an elapsed time (``perf_counter() - start < BOUND``) forms a
chain: the elapsed bound, then the longest blocking ``sleep`` of at least 1 second
in the test or a module-level helper it calls, then the test's outer bound, each
strictly larger than the last. Its fit is the elapsed fit followed by the next
ladder step for each later link, and the test's own marker takes the chain's last
fit.

Each bound prints as ``FLAG path:line owner text worst=W fit=F``: ``LOOSE`` above
its fit, ``TIGHT`` under five times the worst time (and under its fit), ``subject?``
under 1 second (likely the value under test, not a bound), ``unmeasured`` without
a duration, else ``ok``; an unmeasured bound prints ``worst=- fit=-``, and
``fit=>30`` means no ladder step is large enough. Each chain prints as ``FLAG
path:line owner chain A < B < C worst=W fit=X<Y<Z`` with ``CHAIN`` when its links
do not strictly increase, ``LOOSE`` when a link sits above its fit, else ``ok``.
TEST_FILE defaults to every ``tests/**/test_*.py``. Always exits 0.
"""

from __future__ import annotations

import argparse
import ast
import re
from collections import defaultdict
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from riko.base._paths import ROOT_DIR, TESTS_DIR
from riko.cli._lint_tests import (
    BLOCKING_CALLS,
    BOUND_CALLS,
    TIMEOUT_LADDER,
    Bound,
    gen_bounds,
    gen_module_constants,
    get_backstop,
    get_leaf,
    get_seconds,
)
from riko.cli._lint_tests import gen_scopes as gen_lint_scopes

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)s\s+(call|setup|teardown)\s+(.+?)\s*$")
_ELAPSED_CALLS = frozenset({"perf_counter", "monotonic", "time"})
_FACTOR = 5
_FLOOR = 1
_LADDER = sorted(TIMEOUT_LADDER)
_DEFAULT_BACKSTOP = 30


class Link(NamedTuple):
    """One link of an elapsed chain: what sets it and its seconds."""

    text: str
    seconds: float


def parse_durations(*texts: str) -> dict[str, float]:
    worst: defaultdict[str, float] = defaultdict(float)

    for text in texts:
        for line in text.splitlines():
            match = _DURATION.match(line)

            if match is not None and match[2] == "call":
                test = match[3].split("[", 1)[0]
                worst[test] = max(worst[test], float(match[1]))

    return dict(worst)


def get_fit(worst: float) -> int | None:
    needed = max(_FACTOR * worst, _FLOOR)
    return next((s for s in _LADDER if s >= needed), None)


def get_step_above(seconds: float) -> int | None:
    return next((s for s in _LADDER if s > seconds), None)


def get_step_below(seconds: float) -> int | None:
    return next((s for s in reversed(_LADDER) if s < seconds), None)


def get_capped_fit(worst: float, cap: float | None) -> int | None:
    fit = get_fit(worst)
    below = None if cap is None else get_step_below(cap)

    if below is not None and (fit is None or fit > below):
        fit = below

    return fit


def get_flag(seconds: float, worst: float | None, cap: float | None = None) -> str:
    fit = None if worst is None else get_capped_fit(worst, cap)

    if seconds < _FLOOR:
        flag = "subject?"
    elif worst is None:
        flag = "unmeasured"
    elif fit is not None and seconds > fit:
        flag = "LOOSE"
    elif seconds < _FACTOR * worst and (fit is None or seconds < fit):
        flag = "TIGHT"
    else:
        flag = "ok"

    return flag


def get_marker_flag(seconds: float, worst: float | None, chained: int | None) -> str:
    if chained is None or worst is None:
        flag = get_flag(seconds, worst)
    elif seconds > chained:
        flag = "LOOSE"
    elif seconds < chained:
        flag = "TIGHT"
    else:
        flag = "ok"

    return flag


def get_worst(durations: Mapping[str, float], test: str) -> float | None:
    times = [t for k, t in durations.items() if k == test or k.startswith(f"{test}::")]
    return max(times) if times else None


def get_fit_text(worst: float | None, cap: float | None = None) -> str:
    fit = None if worst is None else get_capped_fit(worst, cap)

    if worst is None:
        text = "-"
    elif fit is None:
        text = f">{max(TIMEOUT_LADDER)}"
    else:
        text = str(fit)

    return text


def gen_blocks(
    function: ast.AST, bounds: Mapping[int, Bound]
) -> Iterator[tuple[ast.With | ast.AsyncWith, Bound]]:
    for node in ast.walk(function):
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                call = item.context_expr
                is_block = (
                    isinstance(call, ast.Call) and get_leaf(call.func) in BOUND_CALLS
                )

                if is_block and (bound := bounds.get(call.lineno)) is not None:
                    yield node, bound


def get_block_cap(
    lineno: int, blocks: Iterable[tuple[ast.With | ast.AsyncWith, Bound]]
) -> Link | None:
    around = [
        (node, bound)
        for node, bound in blocks
        if node.lineno < lineno <= (node.end_lineno or node.lineno)
    ]
    innermost = max(around, key=lambda pair: pair[0].lineno, default=None)
    return None if innermost is None else Link(innermost[1].text, innermost[1].seconds)


def get_link_text(node: ast.expr, seconds: float) -> str:
    text = ast.unparse(node)
    return f"{text}={seconds:g}" if isinstance(node, ast.Name) else text


def is_elapsed(node: ast.expr) -> bool:
    calls = (n for n in ast.walk(node) if isinstance(n, ast.Call))
    names = (n.id for n in ast.walk(node) if isinstance(n, ast.Name))
    has_clock = any(get_leaf(call.func) in _ELAPSED_CALLS for call in calls)
    return has_clock or any("elapsed" in name for name in names)


def gen_elapsed(
    function: ast.AST, constants: Mapping[str, float]
) -> Iterator[tuple[int, Link]]:
    for node in ast.walk(function):
        test = node.test if isinstance(node, ast.Assert) else None
        is_upper = (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], (ast.Lt, ast.LtE))
        )

        if is_upper and isinstance(test, ast.Compare) and is_elapsed(test.left):
            comparator = test.comparators[0]
            seconds = get_seconds(comparator, constants)

            if seconds is not None:
                text = f"elapsed<{get_link_text(comparator, seconds)}"
                yield node.lineno, Link(text, seconds)


def get_block(
    function: ast.AST, helpers: Mapping[str, ast.AST], constants: Mapping[str, float]
) -> Link | None:
    seen: set[str] = set()
    pending = [function]
    sleeps: list[Link] = []

    while pending:
        current = pending.pop()

        for node in ast.walk(current):
            if (
                isinstance(node, ast.Name)
                and node.id in helpers
                and node.id not in seen
            ):
                seen.add(node.id)
                pending.append(helpers[node.id])

            is_sleep = (
                isinstance(node, ast.Call) and get_leaf(node.func) in BLOCKING_CALLS
            )

            if is_sleep and isinstance(node, ast.Call) and node.args:
                seconds = get_seconds(node.args[0], constants)

                if seconds is not None and seconds >= _FLOOR:
                    arg = get_link_text(node.args[0], seconds)
                    text = f"{get_leaf(node.func)}({arg})"
                    sleeps.append(Link(text, seconds))

    return max(sleeps, key=lambda link: link.seconds, default=None)


def get_chain_fit(worst: float, size: int) -> list[int | None]:
    fits: list[int | None] = [get_fit(worst)]

    while len(fits) < size:
        last = fits[-1]
        fits.append(None if last is None else get_step_above(last))

    return fits


def get_step_text(step: int | None) -> str:
    return "-" if step is None else str(step)


def get_chain_flag(links: list[Link], fits: list[int | None] | None) -> str:
    seconds = [link.seconds for link in links]
    ordered = all(a < b for a, b in pairwise(seconds))

    if not ordered:
        flag = "CHAIN"
    elif fits is None:
        flag = "unmeasured"
    elif any(f is not None and s > f for s, f in zip(seconds, fits, strict=True)):
        flag = "LOOSE"
    else:
        flag = "ok"

    return flag


def load_backstop_seconds(root: Path) -> float:
    """Loads the suite-wide pytest timeout from pyproject, or the default."""
    pyproject = root / "pyproject.toml"
    text = pyproject.read_text() if pyproject.exists() else ""
    backstop = get_backstop(text)
    return _DEFAULT_BACKSTOP if backstop is None else backstop


class Scope(NamedTuple):
    """One test function with what bounds it: its outer link and worst time."""

    owner: str
    function: ast.AST
    outer: Link
    worst: float | None

    @property
    def worst_text(self) -> str:
        return "-" if self.worst is None else f"{self.worst:.2f}"


def gen_scopes(
    name: str, tree: ast.Module, durations: Mapping[str, float], backstop: float
) -> Iterator[Scope]:
    constants = dict(gen_module_constants(tree))

    for scope in gen_lint_scopes(tree, constants):
        if scope.function is not None:
            seconds, source = scope.get_outer(backstop)
            label = "timeout" if source == "timeout marker" else "pyproject"
            outer = Link(f"{label}({seconds:g})", seconds)
            worst = get_worst(durations, f"{name}::{scope.owner}")
            yield Scope(scope.owner, scope.function, outer, worst)


def gen_chain_rows(
    name: str, tree: ast.Module, scope: Scope
) -> Iterator[tuple[int, str, int | None]]:
    constants = dict(gen_module_constants(tree))
    function_nodes = (ast.FunctionDef, ast.AsyncFunctionDef)
    helpers = {n.name: n for n in tree.body if isinstance(n, function_nodes)}
    block = get_block(scope.function, helpers, constants)

    for lineno, elapsed in gen_elapsed(scope.function, constants):
        links = [elapsed, *([] if block is None else [block]), scope.outer]
        worst = scope.worst
        fits = None if worst is None else get_chain_fit(worst, len(links))
        fit_text = "-" if fits is None else "<".join(map(get_step_text, fits))
        chain = " < ".join(link.text for link in links)
        flag = get_chain_flag(links, fits)
        row = (
            f"{flag:8} {name}:{lineno} {scope.owner} chain {chain} "
            f"worst={scope.worst_text} fit={fit_text}"
        )
        yield lineno, row, None if fits is None else fits[-1]


def get_bound_row(
    name: str, scope: Scope, bound: Bound, cap: Link | None, chained: int | None
) -> str:
    worst = scope.worst

    if cap is None:
        fit_text = get_fit_text(worst) if chained is None else str(chained)
        flag = get_marker_flag(bound.seconds, worst, chained)
        cap_text = ""
    else:
        fit_text = get_fit_text(worst, cap.seconds)
        capped = worst is not None and get_capped_fit(worst, cap.seconds) != get_fit(
            worst
        )
        cap_text = f" cap={cap.text}" if capped else ""
        flag = get_flag(bound.seconds, worst, cap.seconds)

    return (
        f"{flag:8} {name}:{bound.lineno} {scope.owner} {bound.text} "
        f"worst={scope.worst_text} fit={fit_text}{cap_text}"
    )


def gen_file_report(
    name: str, tree: ast.Module, durations: Mapping[str, float], backstop: float
) -> Iterator[str]:
    scopes = {s.owner: s for s in gen_scopes(name, tree, durations, backstop)}
    by_owner: defaultdict[str, list[tuple[Bound, bool]]] = defaultdict(list)
    rows: list[tuple[int, str]] = []
    chain_fits: dict[str, int | None] = {}

    for owner, bound, is_marker in gen_bounds(tree):
        by_owner[owner].append((bound, is_marker))

    for scope in scopes.values():
        for lineno, row, fit in gen_chain_rows(name, tree, scope):
            rows.append((lineno, row))
            chain_fits[scope.owner] = fit

    for owner, items in by_owner.items():
        worst = get_worst(durations, f"{name}::{owner}")
        scope = scopes.get(owner) or Scope(owner, ast.Pass(), Link("", 0), worst)
        inner = {b.lineno: b for b, is_marker in items if not is_marker}
        blocks = list(gen_blocks(scope.function, inner))

        for bound, is_marker in items:
            block = None if is_marker else get_block_cap(bound.lineno, blocks)
            cap = None if is_marker else block or scope.outer
            row = get_bound_row(name, scope, bound, cap, chain_fits.get(owner))
            rows.append((bound.lineno, row))

    for _, row in sorted(rows, key=lambda r: r[0]):
        yield row


def gen_report(
    paths: Iterable[Path], durations: Mapping[str, float], root: Path = ROOT_DIR
) -> Iterator[str]:
    names = {
        path.resolve().relative_to(root.resolve()).as_posix(): path for path in paths
    }
    backstop = load_backstop_seconds(root)

    for name in sorted(names):
        tree = ast.parse(names[name].read_text())
        yield from gen_file_report(name, tree, durations, backstop)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").strip().splitlines()[0]
    )
    parser.add_argument("durations", nargs="+", type=Path)
    parser.add_argument("--files", nargs="+", type=Path)
    args = parser.parse_args(argv)
    durations = parse_durations(*(p.read_text() for p in args.durations))
    paths = args.files or TESTS_DIR.rglob("test_*.py")

    for line in gen_report(paths, durations):
        print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
