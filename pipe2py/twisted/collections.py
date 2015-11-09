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


class AsyncPipe(PyPipe):
    """An asynchronous PyPipe object"""
    def __init__(self, name=None, context=None, **kwargs):
        super(AsyncPipe, self).__init__(name, context)
        self.pipe_input = kwargs.pop('input', asyncPipeForever())
        self.pipeline = getattr(self.module, 'asyncPipe%s' % self.name.title())
        self.kwargs = kwargs

    @property
    @inlineCallbacks
    def list(self):
        output = yield self.output
        returnValue(list(output))

    def pipe(self, name, **kwargs):
        return AsyncPipe(name, self.context, input=self.output, **kwargs)

    def loop(self, name, **kwargs):
        embed = AsyncPipe(name, self.context).pipeline
        return self.pipe('loop', embed=embed, **kwargs)


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
