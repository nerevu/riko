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
from pipe2py.lib.utils import combine_dicts as cdicts, multiplex, remove_keys, group_by
from pipe2py.lib.log import Logger

logger = Logger(__name__).logger


class PyPipe(object):
    """A pipe2py module fetching object"""
    def __init__(self, name, source=None, context=None, **kwargs):
        self.name = name

        if kwargs.pop('listize', False) and source:
            self.source = list(source)
        else:
            self.source = source

        self.context = context or Context()
        self.parallel = kwargs.pop('parallel', False)
        self.threads = kwargs.pop('threads', True)
        self.kwargs = kwargs


class SyncPipe(PyPipe):
    """A synchronous Pipe object"""
    def __init__(self, name, workers=None, chunksize=None, pool=None, **kwargs):
        super(SyncPipe, self).__init__(name, **kwargs)
        self.module = import_module('pipe2py.modules.pipe%s' % self.name)
        self.pipe = self.module.pipe
        self.processor = self.pipe.func_dict.get('sub_type') == 'processor'
        self.reuse_pool = kwargs.get('reuse_pool', True)

        if self.parallel:
            ordered = kwargs.get('ordered')
            funcs = (len, lambda x: getattr(x, '__length_hint__')())
            errors = (TypeError, AttributeError)
            zipped = zip(funcs, errors)
            length = multi_try(self.source, zipped, default=50)
            def_pool = ThreadPool if self.threads else Pool

            self.workers = workers or get_worker_cnt(length, self.threads)
            self.chunksize = chunksize or get_chunksize(length, self.workers)
            self.pool = pool or def_pool(self.workers)
            self.map = self.pool.imap if ordered else self.pool.imap_unordered
        else:
            self.workers = workers
            self.chunksize = chunksize
            self.pool = pool
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

        if self.processor and self.parallel and self.threads:
            mapped = self.map(pipeline, self.source, chunksize=self.chunksize)
        elif self.processor and self.parallel:
            source = izip(self.source, repeat(pipeline))
            mapped = self.map(listpipe, source, chunksize=self.chunksize)
        elif self.processor:
            mapped = self.map(pipeline, self.source)

        if self.parallel and not self.reuse_pool:
            self.pool.close()
            self.pool.join()

        return multiplex(mapped) if self.processor else pipeline(self.source)

    @property
    def list(self):
        return list(self.output)


class PyCollection(object):
    """A pipe2py bulk url fetching object"""
    def __init__(self, sources, parallel=False, thread_cnt=None):
        self.sources = sources
        self.parallel = parallel
        self.thread_cnt = thread_cnt



class SyncCollection(PyCollection):
    """A synchronous PyCollection object"""
    def __init__(self, *args, **kwargs):
        super(SyncCollection, self).__init__(*args, **kwargs)

        if self.parallel:
            length = len(self.sources)
            workers = self.thread_cnt or get_worker_cnt(length)
            self.chunksize = get_chunksize(length, workers)
            self.pool = ThreadPool(workers)
            self.map = self.pool.imap_unordered

    def fetch(self):
        """Fetch all source urls"""
        if self.parallel:
            mapped = self.map(get_pipe, self.sources, chunksize=self.chunksize)
        else:
            mapped = imap(get_pipe, self.sources)

        return multiplex(mapped)

    @property
    def list(self):
        return list(self.fetch())

class Chainable(object):
    def __init__(self, data, method=None):
        self.data = data
        self.method = method
        self.list = list(data)

    def __getattr__(self, name):
        funcs = (partial(getattr, x) for x in [self.data, builtins, itertools])
        zipped = izip(funcs, repeat(AttributeError))
        method = multi_try(name, zipped, default=None)
        return Chainable(self.data, method)

    def __call__(self, *args, **kwargs):
        try:
            return Chainable(self.method(self.data, *args, **kwargs))
        except TypeError:
            return Chainable(self.method(args[0], self.data, **kwargs))


def make_conf(value, conf_type='text'):
    return {'value': value, 'type': conf_type}


def get_chunksize(length, workers):
    return (length // (workers * 4)) + 1


def get_worker_cnt(length, threads=True):
    multiplier = 1.5 if threads else 1
    return int(max(length / 4, cpu_count() * multiplier))


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


def listpipe(args):
    source, pipeline = args
    return list(pipeline(source))


def get_pipe(source, pipe=SyncPipe):
    ptype = source.get('type', 'fetch')
    conf = {k: make_conf(v) for k, v in source.items()}
    return pipe(ptype, conf=conf).list

