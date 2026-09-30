"""Benchmark command for timing sync, async, and parallel pipe execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator, Sequence
from functools import partial
from itertools import chain
from multiprocessing import Pool
from multiprocessing.dummy import Pool as ThreadPool
from time import sleep, time
from timeit import repeat
from typing import TYPE_CHECKING

from riko.bado._backend import async_sleep, isasync
from riko.bado._backend import run as async_run
from riko.bado.itertools import async_map
from riko.base._paths import get_path
from riko.definitions._workflow import Pipeline
from riko.execution._pools import get_chunksize, get_worker_cnt
from riko.modules.fetch import async_pipe as async_fetch
from riko.modules.fetch import pipe as fetch
from riko.runtime._normalize import normalize_workflow
from riko.types._rss import RSSEntry
from riko.types.modules import FetchConf

if TYPE_CHECKING:
    from riko.definitions._workflow import WorkflowSpec
    from riko.types._streams import Item, Items
    from riko.types._workflow import EdgeAuthoring, NodeAuthoring, WorkflowAuthoring
    from riko.types._wrappers import (
        ParserMaterializedOutput,
        SyncProcessorWrapperOutput,
    )

NUMBER = 1
LOOPS = 1
DELAY = 0.1
UNION_ID = "union-1"

files: list[str] = [
    "ouseful.xml",
    "feed.xml",
    "delicious.xml",
    "psychemedia_delicious.xml",
    "ouseful_feedburner.xml",
    "TheEdTechie.xml",
    "yodel.xml",
    "gawker.xml",
    "health.xml",
    "topstories.xml",
    "autoblog.xml",
    "fourtitude.xml",
    "greenhughes.xml",
    "psychemedia_slideshare.xml",
]

urls: list[str] = [get_path(f) for f in files]
confs: list[FetchConf] = [FetchConf({"url": url}) for url in urls]
length: int = len(files)
iterable: list[float] = [DELAY for _ in files]

type AsyncFunc = Callable[..., Awaitable[Iterator[RSSEntry]]]
type AsyncTest = Callable[[], Awaitable[object]]


def build_fanin_spec() -> WorkflowSpec:
    """Builds one workflow fanning a fetch of every feed into a single union."""
    nodes: list[NodeAuthoring] = [
        {"id": f"fetch-{pos}", "name": "fetch", "conf": conf}
        for pos, conf in enumerate(confs)
    ]
    edges: list[EdgeAuthoring] = [
        {
            "source": {"node": f"fetch-{pos}", "port": "out"},
            "target": {"node": UNION_ID, "port": "in" if pos == 0 else f"in:{pos}"},
        }
        for pos in range(length)
    ]
    nodes.append({"id": UNION_ID, "name": "union"})
    workflow: WorkflowAuthoring = {
        "nodes": nodes,
        "edges": edges,
        "outputs": {"default": {"node": UNION_ID, "port": "out"}},
    }
    return normalize_workflow(workflow)


fanin_spec: WorkflowSpec = build_fanin_spec()


def baseline_sync() -> list[None]:
    return list(map(sleep, iterable))


def baseline_threads() -> list[None]:
    workers = get_worker_cnt(length)
    chunksize = get_chunksize(length, workers)
    pool = ThreadPool(workers)
    return list(pool.imap_unordered(sleep, iterable, chunksize=chunksize))


def baseline_procs() -> list[None]:
    workers = get_worker_cnt(length, False)
    chunksize = get_chunksize(length, workers)
    pool = Pool(workers)
    return list(pool.imap_unordered(sleep, iterable, chunksize=chunksize))


def sync_pipeline() -> ParserMaterializedOutput:
    pipes = (fetch(conf=conf) for conf in confs)
    return list(chain.from_iterable(pipes))


def sync_pipe() -> Items:
    results: list[Item] = []

    for conf in confs:
        results.extend(Pipeline.from_module("fetch", conf=conf))

    return results


def sync_workflow() -> Items:
    return list(Pipeline(fanin_spec))


async def baseline_async() -> list[None]:
    return await async_map(async_sleep, iterable)


async def delayed_fetch(conf: FetchConf) -> SyncProcessorWrapperOutput:
    await async_sleep(DELAY)
    return await async_fetch({}, conf)


async def async_pipeline() -> list[SyncProcessorWrapperOutput]:
    return await async_map(delayed_fetch, confs)


async def async_pipe() -> Items:
    results: list[Item] = []

    for conf in confs:
        pipeline = Pipeline.from_module("fetch", conf=conf)
        results.extend([item async for item in pipeline])

    return results


async def async_workflow() -> Items:
    return [item async for item in Pipeline(fanin_spec)]


def parse_results(results: Sequence[float]) -> tuple[float, str]:
    switch = {0: "secs", 3: "msecs", 6: "usecs"}
    best = min(results)

    for places in [0, 3, 6]:
        factor = pow(10, places)
        if 1 / best < factor:
            break

    return round(best * factor, 2), switch[places]


def print_time(test: str, max_chars: int, run_time: float, units: str) -> None:
    padded = test.zfill(max_chars).replace("0", " ")
    msg = "{0} - {1} repetitions/loop, best of {2} loops: {3} {4}"
    print(msg.format(padded, NUMBER, LOOPS, run_time, units))


async def run_async(tests: Sequence[AsyncTest], max_chars: int) -> None:
    for test in tests:
        results = []

        for _ in range(LOOPS):
            loop = 0

            for _ in range(NUMBER):
                start = time()
                await test()
                loop += time() - start

            results.append(loop)

        run_time, units = parse_results(results)
        print_time(test.__name__, max_chars, run_time, units)


def main() -> None:
    run = partial(repeat, repeat=LOOPS, number=NUMBER)
    sync_tests = [
        "baseline_sync",
        "baseline_threads",
        "baseline_procs",
        "sync_pipeline",
        "sync_pipe",
        "sync_workflow",
    ]

    if isasync:
        async_tests = [baseline_async, async_pipeline, async_pipe, async_workflow]
        combined_tests = sync_tests + [f.__name__ for f in async_tests]
    else:
        async_tests = []
        combined_tests = sync_tests

    max_chars = max(list(map(len, combined_tests)))

    for test in sync_tests:
        results = run(f"{test}()", setup=f"from riko.cli.benchmark import {test}")
        run_time, units = parse_results(results)
        print_time(test, max_chars, run_time, units)

    if isasync:
        async_run(run_async, async_tests, max_chars)


if __name__ == "__main__":
    main()
