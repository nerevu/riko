#!/usr/bin/env python
# vim: sw=4:ts=4:expandtab

from functools import partial
from itertools import chain
from multiprocessing import Pool
from multiprocessing.dummy import Pool as ThreadPool
from time import sleep, time

from riko import get_path
from riko.bado import coroutine, react, return_value
from riko.bado.itertools import async_map
from riko.bado.util import async_sleep
from riko.collections import (
    AsyncCollection,
    AsyncPipe,
    SyncCollection,
    SyncPipe,
    get_chunksize,
    get_worker_cnt,
)
from riko.modules.fetch import async_pipe, pipe

NUMBER = 1
LOOPS = 1
DELAY = 0.1

files = [
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

urls = [get_path(f) for f in files]
confs = [{"url": url, "sleep": DELAY} for url in urls]
sources = [{"url": url} for url in urls]
length = len(files)
iterable = [DELAY for x in files]


def baseline_sync():
    return list(map(sleep, iterable))


def baseline_threads():
    workers = get_worker_cnt(length)
    chunksize = get_chunksize(length, workers)
    pool = ThreadPool(workers)
    return list(pool.imap_unordered(sleep, iterable, chunksize=chunksize))


def baseline_procs():
    workers = get_worker_cnt(length, False)
    chunksize = get_chunksize(length, workers)
    pool = Pool(workers)
    return list(pool.imap_unordered(sleep, iterable, chunksize=chunksize))


def sync_pipeline():
    pipes = (pipe(conf=conf) for conf in confs)
    return list(chain.from_iterable(pipes))


def sync_pipe():
    streams = (SyncPipe("fetch", conf=conf).list for conf in confs)
    return list(chain.from_iterable(streams))


def sync_collection():
    return SyncCollection(sources, sleep=DELAY).list


def par_sync_collection():
    return SyncCollection(sources, parallel=True, sleep=DELAY).list


def baseline_async():
    return async_map(async_sleep, iterable)


def async_pipeline():
    d = async_map(lambda conf: async_pipe(conf=conf), confs)
    d.addCallbacks(list, print)


def async_pipe2(conf=None):
    asyncCallable = lambda conf: AsyncPipe("fetch", conf=conf).alist
    d = async_map(asyncCallable, confs)
    d.addCallbacks(list, print)


def async_collection():
    return AsyncCollection(sources, sleep=DELAY).alist


def parse_results(results):
    switch = {0: "secs", 3: "msecs", 6: "usecs"}
    best = min(results)

    for places in [0, 3, 6]:
        factor = pow(10, places)
        if 1 / best // factor == 0:
            break

    return round(best * factor, 2), switch[places]


def print_time(test, max_chars, run_time, units):
    padded = test.zfill(max_chars).replace("0", " ")
    msg = "{0} - {1} repetitions/loop, best of {2} loops: {3} {4}"
    print(msg.format(padded, NUMBER, LOOPS, run_time, units))


@coroutine
def run_async(reactor, tests, max_chars):
    for test in tests:
        results = []

        for _i in range(LOOPS):
            loop = 0

            for _j in range(NUMBER):
                start = time()
                yield test()
                loop += time() - start

            results.append(loop)

        run_time, units = parse_results(results)
        print_time(test.__name__, max_chars, run_time, units)

    return_value(None)


def main():
    from timeit import repeat

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

    async_tests = [baseline_async, async_pipeline, async_pipe2, async_collection]
    combined_tests = sync_tests + [f.__name__ for f in async_tests]
    max_chars = max(list(map(len, combined_tests)))

    for test in sync_tests:
        results = run(f"{test}()", setup=f"from riko.cli.benchmark import {test}")
        run_time, units = parse_results(results)
        print_time(test, max_chars, run_time, units)

    react(run_async, [async_tests, max_chars])


if __name__ == "__main__":
    main()
