# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.lib.collections
    ~~~~~~~~~~~~~~~~~~~~~~~

    Provides methods for creating pipe2py pipes
"""

from importlib import import_module
from pipe2py import Context
from pipe2py.modules.pipeforever import pipe_forever

PIPETYPE = 'fetch'


class PyPipe(object):
    """A pipe2py module fetching object"""
    def __init__(self, name=None, context=None):
        self.name = name or PIPETYPE
        self.context = context or Context()
        self.module = import_module('pipe2py.modules.pipe%s' % self.name)

    @property
    def output(self):
        return self.pipeline(self.context, self.pipe_input, **self.kwargs)


class SyncPipe(PyPipe):
    """A synchronous PyPipe object"""
    def __init__(self, name=None, context=None, **kwargs):
        super(SyncPipe, self).__init__(name, context)
        self.pipe_input = kwargs.pop('input', pipe_forever())
        self.pipeline = getattr(self.module, 'pipe_%s' % self.name)
        self.kwargs = kwargs

    @property
    def list(self):
        return list(self.output)

    def pipe(self, name, **kwargs):
        return SyncPipe(name, self.context, input=self.output, **kwargs)

    def loop(self, name, **kwargs):
        embed = SyncPipe(name, self.context).pipeline
        return self.pipe('loop', embed=embed, **kwargs)
