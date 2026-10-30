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
and a class-level marker takes the worst over the class's tests. Each bound
prints as ``FLAG path:line owner text worst=W fit=F``: ``LOOSE`` above its fit,
``TIGHT`` under five times the worst time, ``subject?`` under 1 second (likely
the value under test, not a bound), ``unmeasured`` without a duration, else
``ok``; an unmeasured bound prints ``worst=- fit=-``, and ``fit=>30`` means no
ladder step is large enough. TEST_FILE defaults to every ``tests/**/test_*.py``.
Always exits 0.
"""

from __future__ import annotations

import argparse
import ast
import re
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from riko.base._paths import ROOT_DIR, TESTS_DIR
from riko.cli._lint_tests import TIMEOUT_LADDER, gen_bounds

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)s\s+(call|setup|teardown)\s+(.+?)\s*$")
_FACTOR = 5
_FLOOR = 1


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
    return next((s for s in sorted(TIMEOUT_LADDER) if s >= needed), None)


def get_flag(seconds: float, worst: float | None) -> str:
    fit = None if worst is None else get_fit(worst)

    if seconds < _FLOOR:
        flag = "subject?"
    elif worst is None:
        flag = "unmeasured"
    elif fit is not None and seconds > fit:
        flag = "LOOSE"
    elif seconds < _FACTOR * worst:
        flag = "TIGHT"
    else:
        flag = "ok"

    return flag


def get_worst(durations: Mapping[str, float], test: str) -> float | None:
    times = [t for k, t in durations.items() if k == test or k.startswith(f"{test}::")]
    return max(times) if times else None


def get_fit_text(worst: float | None) -> str:
    fit = None if worst is None else get_fit(worst)

    if worst is None:
        text = "-"
    elif fit is None:
        text = f">{max(TIMEOUT_LADDER)}"
    else:
        text = str(fit)

    return text


def gen_report(
    paths: Iterable[Path], durations: Mapping[str, float], root: Path = ROOT_DIR
) -> Iterator[str]:
    names = {
        path.resolve().relative_to(root.resolve()).as_posix(): path for path in paths
    }

    for name in sorted(names):
        tree = ast.parse(names[name].read_text())

        for owner, bound, _ in sorted(gen_bounds(tree), key=lambda b: b[1].lineno):
            worst = get_worst(durations, f"{name}::{owner}")
            worst_text = "-" if worst is None else f"{worst:.2f}"
            yield (
                f"{get_flag(bound.seconds, worst):8} {name}:{bound.lineno} {owner} "
                f"{bound.text} worst={worst_text} fit={get_fit_text(worst)}"
            )


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
