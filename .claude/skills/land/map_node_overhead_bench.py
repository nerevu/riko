"""
Measures the per-item cost of each chained ``Pipeline.map`` node.

Purpose: input for a map-fusion decision (``p.map(f).map(g)`` vs ``p.map(g∘f)``),
which the functor composition law allows only where identity semantics agree.
Inputs: optional item count (default 5000) and chain lengths (default 1 2 4 8).
Outputs: one line per chain length, total ms and µs per item, sync mode.
Origin: 2026-11-14 /audit (functor/data-last applicability); promoted from drafts
2026-11-14.
"""

import sys
import timeit

from riko.runtime._pipeline import Pipeline


def identity(item: object) -> object:
    return item


def main() -> None:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    lengths = [int(n) for n in sys.argv[2:]] or [1, 2, 4, 8]
    items = [{"x": i} for i in range(count)]

    for length in lengths:
        pipeline = Pipeline()

        for _ in range(length):
            pipeline = pipeline.map(identity)

        timings = timeit.repeat(lambda p=pipeline: list(p(items)), number=3, repeat=3)
        best = min(timings) / 3
        print(f"{length} maps: {best * 1e3:.1f} ms, {best / count * 1e6:.2f} µs/item")


if __name__ == "__main__":
    main()
