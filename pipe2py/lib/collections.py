# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.lib.collections
~~~~~~~~~~~~~~~~~~~~~~~
Provides methods for creating pipe2py pipes

Examples:
    basic usage::

        >>> from pipe2py.lib.collections import SyncPipe
        >>> from pipe2py import get_url
        >>>
        >>> conf = {'url': get_url('gigs.json'), 'path': 'value.items'}
        >>> skwargs = {'field': 'description', 'delimeter': '<br>'}
        >>> (SyncPipe('fetchdata', conf=conf)
        ...     .sort().stringtokenizer(**skwargs).count().list)
        [{u'content': 343}]
        >>> (SyncPipe('fetchdata', conf=conf, parallel=True)
        ...     .sort().stringtokenizer(**skwargs).count().list)
        [{u'content': 343}]
        >>> (SyncPipe('fetchdata', conf=conf, parallel=True, threads=False)
        ...     .sort().stringtokenizer(**skwargs).count().list)
        [{u'content': 343}]
        >>> conf['type'] = 'fetchdata'
        >>> sources = [{'url': get_url('feed.xml')}, conf]
        >>> len(SyncCollection(sources).list)
        56
        >>> len(SyncCollection(sources, parallel=True).list)
        56
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

import itertools

try:
    import builtins
except ImportError:
    import __builtin__ as builtins

from functools import partial
from itertools import imap, izip, repeat
from importlib import import_module
from multiprocessing.dummy import Pool as ThreadPool
from multiprocessing import Pool, cpu_count

from pipe2py import Context, modules
from pipe2py.lib.utils import multiplex
from pipe2py.lib.log import Logger

logger = Logger(__name__).logger


class PyPipe(object):
    """A pipe2py module fetching object"""
    def __init__(self, name, context=None, parallel=False, **kwargs):
        self.name = name
        self.context = context or Context()
        self.parallel = parallel
        self.kwargs = kwargs


class SyncPipe(PyPipe):
    """A synchronous Pipe object"""
    def __init__(self, name, source=None, workers=None, chunksize=None, **kwargs):
        super(SyncPipe, self).__init__(name, **kwargs)

        if kwargs.pop('listize', False) and source:
            self.source = list(source)
        else:
            self.source = source

        self.threads = kwargs.get('threads', True)
        self.reuse_pool = kwargs.get('reuse_pool', True)
        self.pool = kwargs.get('pool')
        self.module = import_module('pipe2py.modules.pipe%s' % self.name)
        self.pipe = self.module.pipe
        self.processor = self.pipe.func_dict.get('sub_type') == 'processor'

        if self.parallel and self.processor:
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
            self.map = imap

    def __getattr__(self, name):
        kwargs = {
            'parallel': self.parallel,
            'threads': self.threads,
            'pool': self.pool if self.reuse_pool else None,
            'reuse_pool': self.reuse_pool,
            'workers': self.workers}

        return SyncPipe(name, context=self.context, source=self.output, **kwargs)

    def __call__(self, context=None, **kwargs):
        self.context = context or self.context
        self.kwargs = kwargs
        return self

    @property
    def output(self):
        pipeline = partial(self.pipe, context=self.context, **self.kwargs)

        if self.parallel and self.processor:
            zipped = izip(self.source, repeat(pipeline))
            mapped = self.map(listpipe, zipped, chunksize=self.chunksize)
        elif self.processor:
            mapped = self.map(pipeline, self.source)

        if self.parallel and self.processor and not self.reuse_pool:
            self.pool.close()
            self.pool.join()

        return multiplex(mapped) if self.processor else pipeline(self.source)

    @property
    def list(self):
        return list(self.output)


class PyCollection(object):
    """A pipe2py bulk url fetching object"""
    def __init__(self, sources, parallel=False, workers=None, **kwargs):
        self.sources = sources
        self.parallel = parallel
        self.workers = workers
        self.sleep = kwargs.get('sleep', 0)
        self.zargs = izip(self.sources, repeat(self.sleep))
        self.length = lenish(self.sources)
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
            self.map = imap

    def fetch(self):
        """Fetch all source urls"""
        kwargs = {'chunksize': self.chunksize} if self.parallel else {}
        mapped = self.map(getpipe, self.zargs, **kwargs)
        return multiplex(mapped)

    @property
    def list(self):
        return list(self.fetch())


def make_conf(value, conf_type='text'):
    return {'value': value, 'type': conf_type}


def get_chunksize(length, workers):
    return (length // (workers * 4)) or 1


def get_worker_cnt(length, threads=True):
    multiplier = 2 if threads else 1
    return min(length or 1, cpu_count() * multiplier)


def multi_try(source, zipped, default=None):
    value = None

    for func, error in zipped:
        try:
            value = func(source)
        except error:
            pass
        else:
            return value
    else:
        return default

def lenish(source, default=50):
    funcs = (len, lambda x: getattr(x, '__length_hint__')())
    errors = (TypeError, AttributeError)
    zipped = zip(funcs, errors)
    return multi_try(source, zipped, default)


def listpipe(args):
    source, pipeline = args
    return list(pipeline(source))


def getpipe(args, pipe=SyncPipe):
    source, sleep = args
    ptype = source.get('type', 'fetch')
    conf = {k: make_conf(v) for k, v in source.items()}
    conf['sleep'] = make_conf(sleep, 'int')
    return pipe(ptype, conf=conf).list

