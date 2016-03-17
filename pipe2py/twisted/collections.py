# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.twisted.collections
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides methods for creating asynchronous pipe2py pipes

Examples:
    basic usage::

        >>> from twisted.internet.task import react
        >>> from pipe2py.twisted.collections import AsyncPipe, AsyncCollection
        >>> from pipe2py import get_url
        >>>
        >>> url = {'value': get_url('gigs.json')}
        >>> conf = {'url': url, 'path': 'value.items'}
        >>> skwargs = {
        ...     'field': 'description', 'delimiter': '<br>', 'emit': True}
        >>>
        >>> @inlineCallbacks
        ... def run(reactor):
        ...     d1 = yield (AsyncPipe('fetchdata', conf=conf)
        ...         .sort().stringtokenizer(**skwargs).count().list)
        ...     print(d1)
        ...
        ...     conf['type'] = 'fetchdata'
        ...     sources = [{'url': {'value': get_url('feed.xml')}}, conf]
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

from twisted.internet.defer import inlineCallbacks, returnValue

from pipe2py.lib.collections import PyPipe, PyCollection, getpipe
from pipe2py.lib.utils import multiplex
from pipe2py.lib.log import Logger
from pipe2py.twisted import utils as tu

logger = Logger(__name__).logger


class AsyncPipe(PyPipe):
    """An asynchronous PyPipe object"""
    def __init__(self, name, source=None, **kwargs):
        super(AsyncPipe, self).__init__(name, **kwargs)
        self.module = import_module('pipe2py.modules.pipe%s' % self.name)
        self.asyncPipe = self.module.asyncPipe
        self.processor = self.asyncPipe.func_dict.get('sub_type') == 'processor'
        self.source = source

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

        if self.processor:
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
