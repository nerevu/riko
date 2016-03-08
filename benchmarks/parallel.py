from __future__ import absolute_import, division, print_function, with_statement

import time

from os import path as p
from itertools import imap
from collections import defaultdict
from multiprocessing.dummy import Pool as ThreadPool
from multiprocessing import Pool

from pipe2py.lib.collections import SyncPipe, SyncCollection, get_chunksize, get_worker_cnt
from pipe2py.lib.utils import get_abspath

parent = p.join(p.abspath(p.dirname(p.dirname(__file__))), 'data')
files = [
    'blog.ouseful.info_feed.xml',
    'feed.xml',
    'feeds.delicious.com_v2_rss_popular?count=3.xml',
    'feeds.delicious.com_v2_rss_popular?count=15.xml',
    'feeds.delicious.com_v2_rss_psychemedia?count=15.xml',
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

get_url = lambda name: 'file://%s' % p.join(parent, name)


class SleepyDict(dict):
    """A dict like object that sleeps for a specified amount of time before
    returning a key
    """
    def __init__(self, *args, **kwargs):
        self.sleep_time = kwargs.pop('sleep_time', 0.2)
        super(SleepyDict, self).__init__(*args, **kwargs)

    def get(self, key, default=None):
        time.sleep(self.sleep_time)
        return super(SleepyDict, self).get(key, default)

sources = [SleepyDict(url=get_url(f)) for f in files]
length = len(files)
iterable = [0.2 for x in files]


def baseline_sync():
    return list(imap(time.sleep, iterable))


def baseline_threads():
    workers = get_worker_cnt(length)
    chunksize =  get_chunksize(length, workers)
    pool = ThreadPool(workers)
    return list(pool.imap_unordered(time.sleep, iterable, chunksize=chunksize))


def baseline_procs():
    workers = get_worker_cnt(length, False)
    chunksize =  get_chunksize(length, workers)
    pool = Pool(workers)

    return list(pool.imap_unordered(time.sleep, iterable, chunksize=chunksize))


def test_sync():
    return SyncCollection(sources).list


def test_threads():
    return SyncCollection(sources, parallel=True).list


def parse_results(results):
    switch = {0: 'secs', 3: 'msecs', 6: 'usecs'}
    best = min(results)

    for places in [0, 3, 6]:
        factor = pow(10, places)
        if 1 / best // factor == 0:
            break

    return round(best * factor, 2), switch[places]

if __name__ == '__main__':
    from timeit import repeat

    NUMBER = 3
    REPEAT = 3
    msg = '%s - %i repetitions, best of %i loops: %s %s'

    setup = ("from __main__ import baseline_sync")
    results = repeat('baseline_sync()', setup=setup, repeat=REPEAT, number=NUMBER)
    frmttd, unit = parse_results(results)
    print(msg % ('baseline_sync', NUMBER, REPEAT, frmttd, unit))

    setup = ("from __main__ import baseline_threads")
    results = repeat('baseline_threads()', setup=setup, repeat=REPEAT, number=NUMBER)
    frmttd, unit = parse_results(results)
    print(msg % ('baseline_threads', NUMBER, REPEAT, frmttd, unit))

    setup = ("from __main__ import baseline_procs")
    results = repeat('baseline_procs()', setup=setup, repeat=REPEAT, number=NUMBER)
    frmttd, unit = parse_results(results)
    print(msg % ('baseline_procs', NUMBER, REPEAT, frmttd, unit))

    setup = ("from __main__ import test_sync")
    results = repeat('test_sync()', setup=setup, repeat=REPEAT, number=NUMBER)
    frmttd, unit = parse_results(results)
    print(msg % ('test_sync', NUMBER, REPEAT, frmttd, unit))

    setup = ("from __main__ import test_threads")
    results = repeat('test_threads()', setup=setup, repeat=REPEAT, number=NUMBER)
    frmttd, unit = parse_results(results)
    print(msg % ('test_threads', NUMBER, REPEAT, frmttd, unit))

