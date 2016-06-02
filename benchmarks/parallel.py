from __future__ import absolute_import, division, print_function, with_statement

from os import path as p
from functools import partial
from multiprocessing.dummy import Pool as ThreadPool
from multiprocessing import Pool
from time import time, sleep

from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.internet.task import react

from riko.lib.collections import (
    SyncPipe, SyncCollection, get_chunksize, get_worker_cnt)

from riko.twisted.collections import AsyncPipe, AsyncCollection
from riko.twisted.utils import asyncImap, asyncSleep
from riko.modules.pipefetch import pipe, asyncPipe

NUMBER = 3
LOOPS = 3
DELAY = 0.2

parent = p.join(p.abspath(p.dirname(p.dirname(__file__))), 'data')
files = [
    'blog.ouseful.info_feed.xml',
    'feed.xml',
    'feeds.delicious.com_v2_rss_popular?count=3.xml',
    'feeds.delicious.com_v2_rss_popular?count=15.xml',
    'feeds.delicious.compsychemedia.xml',
    'feeds.feedburner.com_ouseful.xml',
    'feeds.feedburner.com_TheEdTechie.xml',
    'feeds.feedburner.com_yodelanecdotal.xml',
    'feeds.gawker.com_jalopnik_full.xml',
    'news.yahoo.com_rss_health.xml',
    'news.yahoo.com_rss_topstories.xml',
    'www.autoblog.com_rss.xml',
    'www.fourtitude.com_news_publish_rss.xml',
    'www.greenhughes.com_rssfeed.xml',
    'www.slideshare.net_rss_user_psychemedia.xml']

get_path = lambda name: 'file://%s' % p.join(parent, name)
sources = [{'url': get_path(f)} for f in files]
length = len(files)
conf = {'url': [{'value': get_path(f)} for f in files], 'sleep': DELAY}
iterable = [DELAY for x in files]


def baseline_sync():
    return map(sleep, iterable)


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
    return list(pipe(conf=conf))


def sync_pipe():
    return SyncPipe('fetch', conf=conf).list


def sync_collection():
    return SyncCollection(sources, sleep=DELAY).list


def par_sync_collection():
    return SyncCollection(sources, parallel=True, sleep=DELAY).list


def baseline_async():
    return asyncImap(asyncSleep, iterable)


def async_pipeline():
    d = asyncPipe(conf=conf)
    d.addCallbacks(list, print)
    return d


def async_pipe():
    return AsyncPipe('fetch', conf=conf).list


def async_collection():
    return AsyncCollection(sources, sleep=DELAY).list


def parse_results(results):
    switch = {0: 'secs', 3: 'msecs', 6: 'usecs'}
    best = min(results)

    for places in [0, 3, 6]:
        factor = pow(10, places)
        if 1 / best // factor == 0:
            break

    return round(best * factor, 2), switch[places]


def print_time(test, max_chars, run_time, units):
    padded = test.zfill(max_chars).replace('0', ' ')
    msg = '%s - %i repetitions/loop, best of %i loops: %s %s'
    print(msg % (padded, NUMBER, LOOPS, run_time, units))


@inlineCallbacks
def run_async(reactor, tests, max_chars):
    for test in tests:
        results = []

        for i in range(LOOPS):
            loop = 0

            for j in range(NUMBER):
                start = time()
                yield test()
                loop += time() - start

            results.append(loop)

        run_time, units = parse_results(results)
        print_time(test.func_name, max_chars, run_time, units)

    returnValue(None)

if __name__ == '__main__':
    from timeit import repeat

    run = partial(repeat, repeat=LOOPS, number=NUMBER)
    sync_tests = [
        'baseline_sync', 'baseline_threads', 'baseline_procs', 'sync_pipeline',
        'sync_pipe', 'sync_collection', 'par_sync_collection']

    async_tests = [baseline_async, async_pipeline, async_pipe, async_collection]
    combined_tests = sync_tests + [f.func_name for f in async_tests]
    max_chars = max(map(len, combined_tests))

    for test in sync_tests:
        results = run('%s()' % test, setup='from __main__ import %s' % test)
        run_time, units = parse_results(results)
        print_time(test, max_chars, run_time, units)

    react(run_async, [async_tests, max_chars])
