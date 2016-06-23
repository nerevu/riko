# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.collections.sync
~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for creating asynchronous riko pipes

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.bado import coroutine, react, _issync
        >>> from riko.bado.mock import FakeReactor
        >>> from riko.collections.async import AsyncPipe, AsyncCollection
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
        ...         .stringtokenizer(conf=str_conf, **str_kwargs)
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

import pygogo as gogo

from functools import partial
from importlib import import_module

from builtins import *

from riko.bado import coroutine, return_value
from riko.collections.sync import PyPipe, PyCollection, getpipe
from riko.lib.utils import multiplex
from riko.bado import util as tu, itertools as ait

logger = gogo.Gogo(__name__, monolog=True).logger


class AsyncPipe(PyPipe):
    """An asynchronous PyPipe object"""
    def __init__(self, name=None, source=None, **kwargs):
        super(AsyncPipe, self).__init__(name, **kwargs)
        self.source = source or []

        if self.name:
            self.module = import_module('riko.modules.pipe%s' % self.name)
            self.asyncPipe = self.module.asyncPipe
            pipe_type = self.asyncPipe.__dict__.get('type')
            self.is_processor = pipe_type == 'processor'
            self.mapify = self.is_processor and self.source
        else:
            self.asyncPipe = lambda source, **kw: tu.asyncReturn(source)
            self.mapify = False

    def __getattr__(self, name):
        return AsyncPipe(name, source=self.output)

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self

    @property
    @coroutine
    def output(self):
        source = yield self.source
        asyncPipeline = partial(self.asyncPipe, **self.kwargs)

        if self.mapify:
            mapped = yield ait.asyncImap(asyncPipeline, source)
            output = multiplex(mapped)
        else:
            output = yield asyncPipeline(source)

        return_value(output)

    @property
    @coroutine
    def list(self):
        output = yield self.output
        return_value(list(output))


class AsyncCollection(PyCollection):
    """An asynchronous PyCollection object"""
    @coroutine
    def asyncFetch(self):
        """Fetch all source urls"""
        mapped = yield ait.asyncImap(asyncGetPipe, self.zargs)
        return_value(multiplex(mapped))

    def asyncPipe(self, **kwargs):
        """Return an AsyncPipe primed with the source feed"""
        return AsyncPipe(source=self.asyncFetch(), **kwargs)

    @property
    @coroutine
    def list(self):
        result = yield self.asyncFetch()
        return_value(list(result))


@coroutine
def asyncListPipe(args):
    source, asyncPipeline = args
    output = yield asyncPipeline(source)
    return_value(list(output))


def asyncGetPipe(args):
    source, sleep = args
    return getpipe((source, sleep), pipe=AsyncPipe)
