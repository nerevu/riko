# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.lib.collections
    ~~~~~~~~~~~~~~~~~~~~~~~

    Provides methods for creating pipe2py pipes
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
from itertools import imap
from importlib import import_module
from pipe2py import Context, modules
from pipe2py.lib.utils import combine_dicts as cdicts


class PyPipe(object):
    """A pipe2py module fetching object"""
    def __init__(self, name, context=None):
        self.name = name
        self.context = context or Context()
        self.module = import_module('pipe2py.modules.pipe%s' % self.name)

    @property
    def output(self):
        return self.pipeline(self.context, self.pipe_input, **self.kwargs)


class SyncPipe(PyPipe):
    """A synchronous PyPipe object"""
    def __init__(self, name, context=None, parallel=False, **kwargs):
        super(SyncPipe, self).__init__(name, context)
        self.input = kwargs.pop('input', None)
        self.source = kwargs.pop('source', None)
        self.item = kwargs.pop('item', None)
        self.map = pmap(workers, **kwargs) if parallel else imap
        self.pipeline = getattr(self.module, 'pipe_%s' % self.name)
        self.kwargs = kwargs

    def __getattr__(self, name):
        if name is 'data':
            return self.pipeline(self.context, self.item, **self.kwargs)
        else:
            return SyncPipe(name, source=self.name, input=self.data)

    def __call__(self, **kwargs):
        pipe = partial(SyncPipe, self.name, self.context, **kwargs)
        get_data = lambda item: pipe(item=item).data
        item = self.map(get_data, self.input)
        return SyncPipe('output', item=item)

    @property
    def list(self):
        return list(self.output)

    def pipe(self, name, **kwargs):
        return SyncPipe(name, self.context, input=self.output, **kwargs)

    def reducer(self, item, arg):
        name, kwargs = arg
        pkwargs = cdicts(kwargs, {'item': item})
        return SyncPipe(name, self.context, **pkwargs).data

    def dispatch(self, *args, **kwargs):
        map_func = lambda item: reduce(self.reducer, args, item)
        item = self.map(map_func, self.data)
        return SyncPipe('output', item=item)


class Chainable(object):
    def __init__(self, data, method=None):
        self.data = data
        self.method = method
        self.list = list(data)

    def __getattr__(self, name):
        try:
            method = getattr(self.data, name)
        except AttributeError:
            try:
                method = getattr(builtins, name)
            except AttributeError:
                method = getattr(itertools, name)

        return Chainable(self.data, method)

    def __call__(self, *args, **kwargs):
        try:
            return Chainable(self.method(self.data, *args, **kwargs))
        except TypeError:
            return Chainable(self.method(args[0], self.data, **kwargs))


def make_conf(value, conf_type='text'):
    return {'value': value, 'type': conf_type}


class PyCollection(object):
    """A pipe2py bulk url fetching object"""
    def __init__(self, sources):
        self.sources = sources

    @staticmethod
    def make_kwargs(src_pipes):

       iterator = enumerate(src_pipes)
       return dict(('_OTHER%i' % k, pipe) for k, pipe in iterator)

    def gen_pipes(self, pipe):
        groups = utils.group_by(self.sources, 'type', PIPETYPE)

        for pipe_type, values in groups.iteritems():
            urls = [make_conf(s['url'], 'url') for s in values]
            conf = {'URL': urls}
            conf.update(values[0].get('conf', {}))  # TODO: groupby conf
            yield pipe(pipe_type, conf=conf).output


class SyncCollection(PyCollection):
    """A synchronous PyCollection object"""
    def fetch_all(self):
        """Fetch all source urls"""
        src_pipes = self.gen_pipes(SyncPipe)
        first_pipe = src_pipes.next()
        kwargs = self.make_kwargs(src_pipes)

        if kwargs:
            kwargs.update({'input': first_pipe})
            result = SyncPipe('union', **kwargs).output
        else:
            result = first_pipe

        return result
