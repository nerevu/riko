# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.collections
~~~~~~~~~~~~~~~~
Provides functions for creating (a)synchronous riko flows and streams

Examples:
    sync usage::

        >>> from riko.collections import SyncPipe
        >>> from riko import get_path
        >>>
        >>> url = {'value': get_path('gigs.json')}
        >>> fconf = {'url': url, 'path': 'value.items'}
        >>> str_conf = {'delimiter': '<br>'}
        >>> str_kwargs = {'field': 'description', 'emit': True}
        >>> sort_conf = {'rule': {'sort_key': 'title'}}
        >>>
        >>> (SyncPipe('fetchdata', conf=fconf)
        ...     .sort(conf=sort_conf)
        ...     .tokenizer(conf=str_conf, **str_kwargs)
        ...     .count().list) == [{'count': 169}]
        True
        >>> (SyncPipe('fetchdata', conf=fconf, parallel=True)
        ...     .sort(conf=sort_conf)
        ...     .tokenizer(conf=str_conf, **str_kwargs)
        ...     .count().list) == [{'count': 169}]
        True
        >>> (SyncPipe('fetchdata', conf=fconf, parallel=True, threads=False)
        ...     .sort(conf=sort_conf)
        ...     .tokenizer(conf=str_conf, **str_kwargs)
        ...     .count().list) == [{'count': 169}]
        True
        >>> fconf['type'] = 'fetchdata'
        >>> sources = [{'url': {'value': get_path('feed.xml')}}, fconf]
        >>> len(SyncCollection(sources).list)
        56
        >>> len(SyncCollection(sources, parallel=True).list)
        56

    async usage::

        >>> from riko import get_path
        >>> from riko.bado import coroutine, react, _issync
        >>> from riko.bado.mock import FakeReactor
        >>> from riko.collections import AsyncPipe, AsyncCollection
        >>>
        >>> url = {'value': get_path('gigs.json')}
        >>> fconf = {'url': url, 'path': 'value.items'}
        >>> str_conf = {'delimiter': '<br>'}
        >>> str_kwargs = {'field': 'description', 'emit': True}
        >>> sort_conf = {'rule': {'sort_key': 'title'}}
        >>>
        >>> @coroutine
        ... def run(reactor):
        ...     d1 = yield (AsyncPipe('fetchdata', conf=fconf)
        ...         .sort(conf=sort_conf)
        ...         .tokenizer(conf=str_conf, **str_kwargs)
        ...         .count()
        ...         .list)
        ...
        ...     print(d1 == [{'count': 169}])
        ...
        ...     fconf['type'] = 'fetchdata'
        ...     sources = [{'url': {'value': get_path('feed.xml')}}, fconf]
        ...     d2 = yield AsyncCollection(sources).list
        ...     print(len(d2))
        ...
        >>> if _issync:
        ...     True
        ...     56
        ... else:
        ...     try:
        ...         react(run, _reactor=FakeReactor())
        ...     except SystemExit:
        ...         pass
        True
        56
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from functools import partial
from itertools import repeat
from importlib import import_module
from multiprocessing.dummy import Pool as ThreadPool
from multiprocessing import Pool, cpu_count

import pygogo as gogo

from builtins import *  # noqa pylint: disable=unused-import

from riko.utils import multiplex, multi_try
from riko.bado import coroutine, return_value
from riko.bado import util, itertools as ait
from meza.process import merge

logger = gogo.Gogo(__name__, monolog=True).logger


class PyPipe(object):
    """A riko module fetching object"""
    def __init__(self, name=None, source=None, parallel=False, **kwargs):
        self.name = name
        self.parallel = parallel

        if kwargs.pop('listize', False) and source:
            self.source = list(source)
        else:
            self.source = source or []

        self.kwargs = kwargs

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self


class SyncPipe(PyPipe):
    """A synchronous Pipe object"""
    def __init__(self, name=None, source=None, workers=None, **kwargs):
        super(SyncPipe, self).__init__(name, source, **kwargs)
        chunksize = kwargs.get('chunksize')

        self.threads = kwargs.get('threads', True)
        self.reuse_pool = kwargs.get('reuse_pool', True)
        self.pool = kwargs.get('pool')

        if self.name:
            self.pipe = import_module('riko.modules.%s' % self.name).pipe
            self.is_processor = self.pipe.__dict__.get('type') == 'processor'
            self.mapify = self.is_processor and self.source
            self.parallelize = self.parallel and self.mapify
        else:
            self.pipe = lambda source, **kw: source
            self.mapify = False
            self.parallelize = False

        if self.parallelize:
            ordered = kwargs.get('ordered')
            length = lenish(self.source)
            def_pool = ThreadPool if self.threads else Pool

            self.workers = workers or get_worker_cnt(length, self.threads)
            self.chunksize = chunksize or get_chunksize(length, self.workers)
            self.pool = self.pool or def_pool(self.workers)
            self.map = self.pool.imap if ordered else self.pool.imap_unordered
        else:
            self.workers = workers
            self.chunksize = chunksize
            self.map = map

    def __getattr__(self, name):
        kwargs = {
            'parallel': self.parallel,
            'threads': self.threads,
            'pool': self.pool if self.reuse_pool else None,
            'reuse_pool': self.reuse_pool,
            'workers': self.workers}

        return SyncPipe(name, source=self.output, **kwargs)

    @property
    def output(self):
        pipeline = partial(self.pipe, **self.kwargs)

        if self.parallelize:
            zipped = zip(self.source, repeat(pipeline))
            mapped = self.map(listpipe, zipped, chunksize=self.chunksize)
        elif self.mapify:
            mapped = self.map(pipeline, self.source)

        if self.parallelize and not self.reuse_pool:
            self.pool.close()
            self.pool.join()

        return multiplex(mapped) if self.mapify else pipeline(self.source)

    @property
    def list(self):
        return list(self.output)


class PyCollection(object):
    """A riko bulk url fetching object"""
    def __init__(self, sources, parallel=False, workers=None, **kwargs):
        self.parallel = parallel
        conf = kwargs.get('conf', {})
        self.zargs = zip(sources, repeat(conf))
        self.length = lenish(sources)
        self.workers = workers or get_worker_cnt(self.length)


class SyncCollection(PyCollection):
    """A synchronous PyCollection object"""
    def __init__(self, *args, **kwargs):
        super(SyncCollection, self).__init__(*args, **kwargs)

        if self.parallel:
            self.chunksize = get_chunksize(self.length, self.workers)
            self.pool = ThreadPool(self.workers)
            self.map = self.pool.imap_unordered
        else:
            self.map = map

    def fetch(self):
        """Fetch all source urls"""
        kwargs = {'chunksize': self.chunksize} if self.parallel else {}
        mapped = self.map(getpipe, self.zargs, **kwargs)
        return multiplex(mapped)

    def pipe(self, **kwargs):
        """Return a SyncPipe primed with the source feed"""
        return SyncPipe(source=self.fetch(), **kwargs)

    @property
    def list(self):
        return list(self.fetch())


class AsyncPipe(PyPipe):
    """An asynchronous PyPipe object"""
    def __init__(self, name=None, source=None, connections=16, **kwargs):
        super(AsyncPipe, self).__init__(name, source, **kwargs)
        self.connections = connections

        if self.name:
            self.module = import_module('riko.modules.%s' % self.name)
            self.async_pipe = self.module.async_pipe

            pipe_type = self.async_pipe.__dict__.get('type')
            self.is_processor = pipe_type == 'processor'
            self.mapify = self.is_processor and self.source
        else:
            self.async_pipe = lambda source, **kw: util.async_return(source)
            self.mapify = False

    def __getattr__(self, name):
        return AsyncPipe(name, source=self.output, connections=self.connections)

    @property
    @coroutine
    def output(self):
        source = yield self.source
        async_pipeline = partial(self.async_pipe, **self.kwargs)

        if self.mapify:
            args = (async_pipeline, source, self.connections)
            mapped = yield ait.async_map(*args)
            output = multiplex(mapped)
        else:
            output = yield async_pipeline(source)

        return_value(output)

    @property
    @coroutine
    def list(self):
        output = yield self.output
        return_value(list(output))


class AsyncCollection(PyCollection):
    """An asynchronous PyCollection object"""
    def __init__(self, sources, connections=16, **kwargs):
        super(AsyncCollection, self).__init__(sources, **kwargs)
        self.connections = connections

    @coroutine
    def async_fetch(self):
        """Fetch all source urls"""
        args = (async_get_pipe, self.zargs, self.connections)
        mapped = yield ait.async_map(*args)
        return_value(multiplex(mapped))

    def async_pipe(self, **kwargs):
        """Return an AsyncPipe primed with the source feed"""
        return AsyncPipe(source=self.async_fetch(), **kwargs)

    @property
    @coroutine
    def list(self):
        result = yield self.async_fetch()
        return_value(list(result))


def get_chunksize(length, workers):
    return (length // (workers * 4)) or 1


def get_worker_cnt(length, threads=True):
    multiplier = 2 if threads else 1
    return min(length or 1, cpu_count() * multiplier)


def lenish(source, default=50):
    funcs = (len, lambda x: x.__length_hint__())
    errors = (TypeError, AttributeError)
    zipped = list(zip(funcs, errors))
    return multi_try(source, zipped, default)


def listpipe(args):
    source, pipeline = args
    return list(pipeline(source))


def getpipe(args, pipe=SyncPipe):
    source, conf = args
    ptype = source.get('type', 'fetch')
    return pipe(ptype, conf=merge([conf, source])).output


@coroutine
def async_list_pipe(args):
    source, async_pipeline = args
    output = yield async_pipeline(source)
    return_value(list(output))


async_get_pipe = partial(getpipe, pipe=AsyncPipe)
