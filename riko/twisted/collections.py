# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.twisted.collections
~~~~~~~~~~~~~~~~~~~~~~~~
Provides methods for creating asynchronous riko pipes

Examples:
    basic usage::

        >>> from twisted.internet.task import react
        >>> from riko.twisted.collections import AsyncPipe, AsyncCollection
        >>> from riko import get_path
        >>>
        >>> url = {'value': get_path('gigs.json')}
        >>> fconf = {'url': url, 'path': 'value.items'}
        >>> str_conf = {'delimiter': '<br>'}
        >>> str_kwargs = {'field': 'description', 'emit': True}
        >>> sort_conf = {'rule': {'sort_key': 'title'}}
        >>>
        >>> @inlineCallbacks
        ... def run(reactor):
        ...     d1 = yield (AsyncPipe('fetchdata', conf=fconf)
        ...         .sort(conf=sort_conf)
        ...         .stringtokenizer(conf=str_conf, **str_kwargs)
        ...         .count().list)
        ...
        ...     print(d1)
        ...
        ...     fconf['type'] = 'fetchdata'
        ...     sources = [{'url': {'value': get_path('feed.xml')}}, fconf]
        ...     d2 = yield AsyncCollection(sources).list
        ...     print(len(d2))
        ...
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        [{u'count': 169}]
        56
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from functools import partial
from importlib import import_module

from builtins import *
from twisted.internet.defer import inlineCallbacks, returnValue

from riko.lib.collections import PyPipe, PyCollection, getpipe
from riko.lib.utils import multiplex
from riko.lib.log import Logger
from riko.twisted import utils as tu

logger = Logger(__name__).logger


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
    @inlineCallbacks
    def output(self):
        source = yield self.source
        asyncPipeline = partial(self.asyncPipe, **self.kwargs)

        if self.mapify:
            mapped = yield tu.asyncImap(asyncPipeline, source)
            output = multiplex(mapped)
        else:
            output = yield asyncPipeline(source)

        returnValue(output)

    @property
    @inlineCallbacks
    def list(self):
        output = yield self.output
        returnValue(list(output))


class AsyncCollection(PyCollection):
    """An asynchronous PyCollection object"""
    @inlineCallbacks
    def asyncFetch(self):
        """Fetch all source urls"""
        mapped = yield tu.asyncImap(asyncGetPipe, self.zargs)
        returnValue(multiplex(mapped))

    def asyncPipe(self, **kwargs):
        """Return an AsyncPipe primed with the source feed"""
        return AsyncPipe(source=self.asyncFetch(), **kwargs)

    @property
    @inlineCallbacks
    def list(self):
        result = yield self.asyncFetch()
        returnValue(list(result))


@inlineCallbacks
def asyncListPipe(args):
    source, asyncPipeline = args
    output = yield asyncPipeline(source)
    returnValue(list(output))


def asyncGetPipe(args):
    source, sleep = args
    return getpipe((source, sleep), pipe=AsyncPipe)
