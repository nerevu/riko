# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeoutput
    ~~~~~~~~~~~~~~~~~~~~~~~~~~
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from twisted.internet.defer import inlineCallbacks, returnValue


@inlineCallbacks
def asyncPipeOutput(context=None, item=None, conf=None, **kwargs):
    """An operator that asynchronously outputs the input source, i.e. does
    nothing (for now).

    Parameters
    ----------
    context : pipe2py.Context object
    item : asyncPipe like object (twisted Deferred iterable of items)
    conf : {'format': {'value': <format>}}

    Returns
    ------
    _OUTPUT : item
    """
    # todo: convert to XML, JSON, iCal, KLM, CSV...
    returnValue(item)


def pipe_output(context=None, item=None, conf=None, **kwargs):
    """Outputs the input source, i.e. does nothing (for now).

    Parameters
    ----------
    context : pipe2py.Context object
    item : pipe2py.modules pipe like object (iterable of items)
    conf : {'format': {'value': <format>}}

    Returns
    ------
    _OUTPUT : item
    """
    # todo: convert to XML, JSON, iCal, KLM, CSV...
    return item
