# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.twisted.collections
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Provides methods for creating asynchronous pipe2py pipes
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from twisted.internet.defer import inlineCallbacks, returnValue
from pipe2py.modules.pipeforever import asyncPipeForever
from pipe2py.lib.collections import PyPipe, PyCollection
from functools import partial
from itertools import imap
from twisted.internet.defer import inlineCallbacks, returnValue
from pipe2py.lib.collections import PyPipe
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.twisted import utils as tu


class AsyncPipe(PyPipe):
    """An asynchronous PyPipe object"""
    def __init__(self, name, context=None, parallel=False, **kwargs):
        super(AsyncPipe, self).__init__(name, context)
        self.input = kwargs.pop('input', None)
        self.source = kwargs.pop('source', None)
        self.item = kwargs.pop('item', None)
        self.map = tu.asyncPmap(workers, **kwargs) if parallel else tu.asyncImap
        # self.map = pmap(workers, **kwargs) if parallel else imap
        self.pipeline = getattr(self.module, 'asyncPipe%s' % self.name.title())
        self.kwargs = kwargs

    def __getattr__(self, name):
        if name is 'data':
            return self.pipeline(self.context, self.item, **self.kwargs)
        else:
            return AsyncPipe(name, source=self.name, input=self.data)

    @inlineCallbacks
    def __call__(self, **kwargs):
        embed = self.embed(**kwargs)
        f = partial(AsyncPipe, self.name, self.context, embed=embed, **kwargs)
        map_func = lambda item: f(item=item).data
        _input = yield self.input
        item = yield self.map(map_func, _input)
        returnValue(AsyncPipe('output', item=item))

    @property
    @inlineCallbacks
    def list(self):
        output = yield self.output
        returnValue(list(output))

    def pipe(self, name, **kwargs):
        return AsyncPipe(name, self.context, input=self.output, **kwargs)

    def embed(self, ename=None, **kwargs):
        return AsyncPipe(ename, self.context).pipeline if ename else ename

    def loop(self, name, **kwargs):
        return self.pipe('loop', embed=self.embed(name), **kwargs)

    def reducer(self, item, arg):
        name, kwargs = arg
        embed = self.embed(**kwargs)
        pkwargs = cdicts(kwargs, {'item': item, 'embed': embed})
        return AsyncPipe(name, self.context, **pkwargs).data

    @inlineCallbacks
    def dispatch(self, *args, **kwargs):
        map_func = lambda item: tu.asyncReduce(self.reducer, args, item)
        item = yield self.map(map_func, self.data)
        returnValue(AsyncPipe('output', item=item))


class AsyncCollection(PyCollection):
    """An asynchronous PyCollection object"""
    @inlineCallbacks
    def asyncFetchAll(self):
        """Fetch all source urls"""
        src_pipes = self.gen_pipes(AsyncPipe)
        first_pipe = src_pipes.next()
        kwargs = self.make_kwargs(src_pipes)

        if kwargs:
            kwargs.update({'input': first_pipe})
            result = yield AsyncPipe('union', **kwargs).output
        else:
            result = yield first_pipe

        returnValue(result)
