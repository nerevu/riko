# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeforever
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Provides methods for mocking an input source. This enables other modules,
    e.g. date builder, to be called so they can continue to consume values from
    indirect terminal inputs.
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from itertools import takewhile, repeat
from pipe2py.twisted.utils import asyncReturn

forever = takewhile(bool, repeat({'forever': True}))


def asyncPipeForever():
    """A source that returns a Deferred infinite generator of items. Loopable.

    Returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of items
    """
    return asyncReturn(forever)


def pipe_forever():
    """A source that returns an infinite generator of items. Loopable.

    Returns
    -------
    _OUTPUT : generator of items
    """
    return forever
