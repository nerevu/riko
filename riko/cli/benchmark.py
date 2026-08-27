from collections.abc import Awaitable, Callable, Iterator
from functools import partial
from itertools import chain
from multiprocessing import Pool
from multiprocessing.dummy import Pool as ThreadPool
from time import sleep, time
from timeit import repeat

from riko import get_path
from riko.bado import async_sleep, isasync
from riko.bado import run as async_run
from riko.bado.itertools import async_map
from riko.collections import (
    AsyncCollection,
    AsyncPipe,
    SyncCollection,
    SyncPipe,
    get_chunksize,
    get_worker_cnt,
)
from riko.modules.fetch import async_pipe as async_fetch
from riko.modules.fetch import pipe as fetch
from riko.types.general import (
    AsyncPipeParser,
    Items,
    ParserMaterializedOutput,
    ProcessorWrapperOutput,
)
from riko.types.modules import FetchConf
from riko.types.values import RSSEntry

NUMBER = 1
LOOPS = 1
DELAY = 0.1

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
sources: list[dict[str, str]] = [{"url": url} for url in urls]
length: int = len(files)
iterable: list[float] = [DELAY for _ in files]

type AsyncFunc = Callable[..., Awaitable[Iterator[RSSEntry]]]


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
    streams = (SyncPipe("fetch", conf=conf) for conf in confs)
    return list(chain.from_iterable(streams))


def sync_collection() -> Items:
    return list(SyncCollection(sources, sleep=DELAY))


def par_sync_collection() -> Items:
    return list(SyncCollection(sources, parallel=True, sleep=DELAY))


async def baseline_async() -> list[None]:
    return await async_map(async_sleep, iterable)


async def delayed_fetch(conf: FetchConf) -> ProcessorWrapperOutput:
    await async_sleep(DELAY)
    return await async_fetch({}, conf)


async def async_pipeline() -> list[ProcessorWrapperOutput]:
    return await async_map(delayed_fetch, confs)


async def async_pipe2() -> list[ProcessorWrapperOutput]:
    func = partial(AsyncPipe, "fetch", iter(()))
    return await async_map(func, confs)


async def async_collection() -> Items:
    results = await AsyncCollection(sources, sleep=DELAY)
    return list(results)


def parse_results(results: list[float]) -> tuple[float, str]:
    switch = {0: "secs", 3: "msecs", 6: "usecs"}
    best = min(results)

    for places in [0, 3, 6]:
        factor = pow(10, places)
        if 1 / best // factor == 0:
            break

    return round(best * factor, 2), switch[places]


def print_time(test: str, max_chars: int, run_time: float, units: str) -> None:
    padded = test.zfill(max_chars).replace("0", " ")
    msg = "{0} - {1} repetitions/loop, best of {2} loops: {3} {4}"
    print(msg.format(padded, NUMBER, LOOPS, run_time, units))


async def run_async(tests: list[AsyncPipeParser], max_chars: int) -> None:
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
        "sync_collection",
        "par_sync_collection",
    ]

    if isasync:
        async_tests = [baseline_async, async_pipeline, async_pipe2, async_collection]
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
