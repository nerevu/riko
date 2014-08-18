# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipecount
    ~~~~~~~~~~~~~~

    Provides methods for counting the number of items in a feed.

    http://pipes.yahoo.com/pipes/docs?doc=operators#Count
"""
from pipe2py import util


def pipe_count(context=None, _INPUT=None, conf=None, **kwargs):
    """Counts the number of _INPUT items and yields it forever.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : source generator of dicts
    conf : not used

    Yields
    ------
    _OUTPUT : number of items in the feed

    """

    count = sum(1 for item in _INPUT)
    # todo: check all operators (not placeable in loops)
    # read _INPUT once only & then serve - in case they serve multiple further
    # steps
    while True:
        yield count
