# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipecount
    ~~~~~~~~~~~~~~

    Provides methods for counting the number of items in a feed.

    http://pipes.yahoo.com/pipes/docs?doc=operators#Count
"""


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

    Examples
    --------
    >>> generator = (x for x in xrange(5))
    >>> count = pipe_count(_INPUT=generator)
    >>> count  #doctest: +ELLIPSIS
    <generator object pipe_count at 0x...>
    >>> count.next()
    5
    >>> from json import loads
    >>> import os.path as p
    >>> file_name = p.join(p.dirname(p.dirname(__file__)), 'data', 'gigs.json')
    >>> json = ''.join(line for line in open(file_name))
    >>> data_raw = loads(json.encode('utf-8'))
    >>> items = data_raw['value']['items']
    """

    count = len(list(_INPUT))
    # todo: check all operators (not placeable in loops)
    # read _INPUT once only & then serve - in case they serve multiple further
    # steps
    while True:
        yield count
