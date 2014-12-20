# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeoutput
    ~~~~~~~~~~~~~~~~~~~~~~~~~~

"""


def pipe_output(context=None, _INPUT=None, conf=None, **kwargs):
    """Outputs the input source, i.e. does nothing (for now).

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
    conf : {'format': {'value': <format>}}

    Yields
    ------
    _OUTPUT : item
    """
    # todo: convert to XML, JSON, iCal, KLM, CSV...
    for item in _INPUT:
        yield item
