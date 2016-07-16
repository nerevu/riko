# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.collections.sync
~~~~~~~~~~~~~~~~~~~~~

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
from riko.bado import util, itertools as ait

logger = gogo.Gogo(__name__, monolog=True).logger


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


@coroutine
def async_list_pipe(args):
    source, async_pipeline = args
    output = yield async_pipeline(source)
    return_value(list(output))


def async_get_pipe(args):
    source, sleep = args
    return getpipe((source, sleep), pipe=AsyncPipe)
