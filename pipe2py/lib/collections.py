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
