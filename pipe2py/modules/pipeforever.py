# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeforever
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Provides methods for mocking an input source. This enables other modules,
    e.g. date builder, to be called so they can continue to consume values from
    indirect terminal inputs.
"""

from __future__ import absolute_import


def forever():
    while True:
        yield {'forever': True}


def pipe_forever():
    """A source that returns an infinite generator of items. Loopable.

    Returns
    -------
    _OUTPUT : generator of items
    """
    _OUTPUT = forever()
    return _OUTPUT
