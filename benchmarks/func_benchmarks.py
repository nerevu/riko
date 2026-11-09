"""
Compare map/repeat, generator, lambda, closure, and partial binding.

Usage:
    uv run --active python benchmarks/func_benchmarks.py

Small: 16 elements; large: 1,000 elements. All single-use timings
include callable construction; *_reused cases bind outside the timed block.
Only the iterable is prebuilt for every case.
"""

import platform
import sys
from functools import partial
from itertools import repeat  # noqa: F401 (the timed statements call it)
from random import Random
from statistics import median
from timeit import Timer


def arg_func(arg: int, kwarg: int = 1) -> int:
    return arg * kwarg + 1


def kw_func(arg: int, *, kwarg: int = 1) -> int:
    return arg * kwarg + 1


class Runner:
    def run(self, arg: int, *, kwarg: int = 1) -> int:
        return arg * kwarg + 1


arg, kwarg = 2, 3
runner = Runner()
bound_arg_reused = partial(arg_func, arg)
bound_kwarg_partial_reused = partial(kw_func, kwarg=kwarg)


def bound_kwarg_reused(item: int) -> int:
    return kw_func(item, kwarg=kwarg)


# Each statement is executed repeatedly; setup outside the statement is
# intentionally excluded from the measurement.
CASES = {
    "arg: repeat": "tuple(map(arg_func, repeat(arg), values))",
    "arg: inline partial": "tuple(map(partial(arg_func, arg), values))",
    "arg: bound once": (
        "bound_arg = partial(arg_func, arg)\ntuple(map(bound_arg, values))"
    ),
    "arg: bound reused": "tuple(map(bound_arg_reused, values))",
    "kw: repeat positional": "tuple(map(arg_func, values, repeat(kwarg)))",
    "kw: generator positional": "tuple(arg_func(item, kwarg) for item in values)",
    "kw: generator keyword": "tuple(kw_func(item, kwarg=kwarg) for item in values)",
    "kw: lambda positional": "tuple(map(lambda item: arg_func(item, kwarg), values))",
    "kw: lambda keyword": (
        "tuple(map(lambda item: kw_func(item, kwarg=kwarg), values))"
    ),
    "kw: named once": (
        "def bound_kwarg(item):\n"
        "    return kw_func(item, kwarg=kwarg)\n"
        "tuple(map(bound_kwarg, values))"
    ),
    "kw: named reused": "tuple(map(bound_kwarg_reused, values))",
    "kw: inline partial": "tuple(map(partial(kw_func, kwarg=kwarg), values))",
    "kw: bound once": (
        "bound_kwarg = partial(kw_func, kwarg=kwarg)\ntuple(map(bound_kwarg, values))"
    ),
    "kw: bound reused": "tuple(map(bound_kwarg_partial_reused, values))",
    "method: generator keyword": (
        "tuple(runner.run(item, kwarg=kwarg) for item in values)"
    ),
    "method: lambda keyword": (
        "tuple(map(lambda item: runner.run(item, kwarg=kwarg), values))"
    ),
    "method: inline partial": "tuple(map(partial(runner.run, kwarg=kwarg), values))",
}


def main() -> None:
    print(f"CPython {sys.version.split()[0]} on {platform.platform()}")
    for size, iterations in ((16, 1_000), (1_000, 30)):
        values = tuple(range(1, size + 1))
        globals_for_timer = {**globals(), "values": values}
        timers = {
            name: Timer(statement, globals=globals_for_timer)
            for name, statement in CASES.items()
        }

        measurements = {name: [] for name in CASES}
        order = list(CASES)
        rng = Random(128)  # ruff: ignore[suspicious-non-cryptographic-random-usage]

        for round_idx in range(90):
            rng.shuffle(order)

            for name in order:
                timer = timers[name]

                if not round_idx:
                    timer.timeit(number=1)  # Warm up.

                seconds = timer.timeit(number=iterations) / iterations
                measurements[name].append(seconds * 1_000_000)

        medians = {name: median(times) for name, times in measurements.items()}

        # The two repeat patterns serve as a common ~1.0x reference.
        baseline = (medians["arg: repeat"] + medians["kw: repeat positional"]) / 2
        print(f"\n{size} elements; reference = {baseline:.3f} us/op")

        for name, us in sorted(medians.items(), key=lambda result: result[1]):
            print(f"{name:26s} {us:8.3f} us/op   {us / baseline:5.2f}x")


if __name__ == "__main__":
    main()
