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
        >>> conf = {'url': get_url('gigs.json'), 'path': 'value.items'}
        >>> skwargs = {'field': 'description', 'delimeter': '<br>'}
        >>>
        >>> @inlineCallbacks
        ... def run(reactor):
        ...     d1 = yield (AsyncPipe('fetchdata', conf=conf)
        ...         .sort().stringtokenizer(**skwargs).count().list)
        ...     d2 = yield (AsyncPipe('fetchdata', conf=conf, coop=True)
        ...         .sort().stringtokenizer(**skwargs).count().list)
        ...     d3 = yield (AsyncPipe('fetchdata', conf=conf, parallel=True)
        ...         .sort().stringtokenizer(**skwargs).count().list)
        ...     print(d1)
        ...     print(d2)
        ...     print(d3)
        ...
        ...     conf['type'] = 'fetchdata'
        ...     sources = [{'url': get_url('feed.xml')}, conf]
        ...     d4 = yield AsyncCollection(sources).list
        ...     d5 = yield AsyncCollection(sources, coop=True).list
        ...     d6 = yield AsyncCollection(sources, parallel=True).list
        ...     print(len(d4))
        ...     print(len(d5))
        ...     print(len(d6))
        ...
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        [{u'content': 343}]
        [{u'content': 343}]
        [{u'content': 343}]
        56
        56
        56
"""

from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from functools import partial
from importlib import import_module
from itertools import izip, repeat

from twisted.internet.defer import inlineCallbacks, returnValue

from pipe2py.lib.collections import PyPipe, PyCollection, multi_try, getpipe, get_worker_cnt
from pipe2py.lib.utils import multiplex
from pipe2py.lib.log import Logger
from pipe2py.twisted import utils as tu

logger = Logger(__name__).logger


class AsyncPipe(PyPipe):
    """An asynchronous PyPipe object"""
    def __init__(self, name, source=None, workers=None, **kwargs):
        super(AsyncPipe, self).__init__(name, **kwargs)
        self.coop = kwargs.get('coop')
        self.module = import_module('pipe2py.modules.pipe%s' % self.name)
        self.asyncPipe = self.module.asyncPipe
        self.processor = self.asyncPipe.func_dict.get('sub_type') == 'processor'
        self.listize = kwargs.pop('listize', False)
        self.source = source
        self.workers = workers

        if self.parallel:
            self.asyncMap = tu.asyncPmap
        else:
            self.asyncMap = tu.asyncCmap if self.coop else tu.asyncImap

    def __getattr__(self, name):
        kwargs = {
            'parallel': self.parallel,
            'coop': self.coop,
            'workers': self.workers}

        return AsyncPipe(name, context=self.context, source=self.output, **kwargs)

    def __call__(self, context=None, **kwargs):
        self.context = context or self.context
        self.kwargs = kwargs
        return self

    @property
    @inlineCallbacks
    def output(self):
        source = yield self.source
        listized = list(source) if self.listize and source else source
        asyncPipeline = partial(self.asyncPipe, context=self.context, **self.kwargs)

        if self.parallel and self.processor and not self.workers:
            funcs = (len, lambda x: getattr(x, '__length_hint__')())
            errors = (TypeError, AttributeError)
            zipped = zip(funcs, errors)
            length = multi_try(listized, zipped, default=50)
            self.workers = get_worker_cnt(length, True)

        if self.processor and self.parallel:
            zipped = izip(listized, repeat(asyncPipeline))
            mapped = yield self.asyncMap(asyncListPipe, zipped, workers=self.workers)
        elif self.processor:
            try:
                mapped = yield self.asyncMap(asyncPipeline, listized)
            except exception as e:
                logger.error(e)

        if self.processor:
            output = multiplex(mapped)
        else:
            output = yield asyncPipeline(listized)

        returnValue(output)

    @property
    @inlineCallbacks
    def list(self):
        output = yield self.output
        returnValue(list(output))


class AsyncCollection(PyCollection):
    """An asynchronous PyCollection object"""
    def __init__(self, *args, **kwargs):
        super(AsyncCollection, self).__init__(*args, **kwargs)
        self.coop = kwargs.get('coop')

        if self.parallel:
            length = len(self.sources)
            self.workers = self.workers or get_worker_cnt(length)
            self.asyncMap = tu.asyncPmap
        else:
            self.asyncMap = tu.asyncCmap if self.coop else tu.asyncImap

    @inlineCallbacks
    def asyncFetch(self):
        """Fetch all source urls"""
        kwargs = {'workers': self.workers} if self.parallel else {}
        mapped = yield self.asyncMap(asyncGetPipe, self.sources, **kwargs)
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


def asyncGetPipe(source):
    return getpipe(source, pipe=AsyncPipe)

