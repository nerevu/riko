# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.modules.pipecsv
~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for fetching csv files.

Examples:
    basic usage::

        >>> from . import FILES
        >>> from pipe2py.modules.pipecsv import pipe
        >>> pipe(conf={'url': FILES[6]}).next()['mileage']
        u'7213'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from urllib2 import urlopen

from meza.io import read_csv
from twisted.internet.defer import inlineCallbacks, returnValue

from . import processor
from pipe2py.lib import utils
from pipe2py.lib.log import Logger
from pipe2py.twisted import utils as tu

OPTS = {'ftype': 'none'}
DEFAULTS = {
    'delimiter': ',', 'quotechar': '"', 'encoding': 'utf-8', 'skip_rows': 0,
    'sanitize': True, 'dedupe': True, 'col_names': None, 'has_header': True}

logger = Logger(__name__).logger


@inlineCallbacks
def asyncParser(_, objconf, skip, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        feed (dict): The original item

    Returns:
        Tuple(Iter[dict], bool): Tuple of (feed, skip)

    Examples:
        >>> from twisted.internet.task import react
        >>> from . import FILES
        >>> from pipe2py.lib.utils import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x[0].next()['mileage'])
        ...     conf = {'url': FILES[6], 'sanitize': True, 'skip_rows': 0}
        ...     objconf = Objectify(conf)
        ...     kwargs = {'feed': {}}
        ...     d = asyncParser(None, objconf, False, **kwargs)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        7213
    """
    if skip:
        feed = kwargs['feed']
    else:
        url = utils.get_abspath(objconf.url)
        f = yield tu.urlOpen(url)
        odd = {
            'first_row': objconf.skip_rows, 'custom_header': objconf.col_names}

        rkwargs = utils.combine_dicts(objconf.to_dict(), odd)
        feed = read_csv(f, **rkwargs)

    result = (feed, skip)
    returnValue(result)


def parser(_, objconf, skip, **kwargs):
    """ Parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content

    Returns:
        Tuple(Iter[dict], bool): Tuple of (feed, skip)

    Examples:
        >>> from . import FILES
        >>> from pipe2py.lib.utils import Objectify
        >>>
        >>> conf = {'url': FILES[6], 'sanitize': True, 'skip_rows': 0}
        >>> objconf = Objectify(conf)
        >>> kwargs = {'feed': {}}
        >>> result, skip = parser(None, objconf, False, **kwargs)
        >>> result.next()['mileage']
        u'7213'
    """
    if skip:
        feed = kwargs['feed']
    else:
        url = utils.get_abspath(objconf.url)
        f = urlopen(url)
        odd = {
            'first_row': objconf.skip_rows, 'custom_header': objconf.col_names}
        rkwargs = utils.combine_dicts(objconf.to_dict(), odd)
        feed = read_csv(f, **rkwargs)

    return feed, skip


@processor(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A source that asynchronously fetches the content of a given web site as
    a string.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'delimiter', 'quotechar', 'encoding', 'skip_rows',
            'sanitize', 'dedupe', 'col_names', or 'has_header'.

            url (str): The csv file to fetch
            delimiter (str): Field delimiter (default: ',').
            quotechar (str): Quote character (default: '"').
            encoding (str): File encoding (default: 'utf-8').
            has_header (bool): Has header row (default: True).
            skip_rows (int): Number of initial rows to skip (zero based,
                default: 0).

            sanitize (bool): Underscorify and lowercase field names
                (default: False).

            dedupe (bool): Deduplicate column names (default: False).
            col_names (List[str]): Custom column names (default: None).

    Returns:
        dict: twisted.internet.defer.Deferred item with feeds

    Examples:
        >>> from twisted.internet.task import react
        >>> from . import FILES
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x.next()['mileage'])
        ...     d = asyncPipe(conf={'url': FILES[6]})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        7213
    """
    return asyncParser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A source that fetches and parses a csv file to yield items.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'delimiter', 'quotechar', 'encoding', 'skip_rows',
            'sanitize', 'dedupe', 'col_names', or 'has_header'.

            url (str): The csv file to fetch
            delimiter (str): Field delimiter (default: ',').
            quotechar (str): Quote character (default: '"').
            encoding (str): File encoding (default: 'utf-8').
            has_header (bool): Has header row (default: True).
            skip_rows (int): Number of initial rows to skip (zero based,
                default: 0).

            sanitize (bool): Underscorify and lowercase field names
                (default: False).

            dedupe (bool): Deduplicate column names (default: False).
            col_names (List[str]): Custom column names (default: None).

    Yields:
        dict: an item on the feed

    Examples:
        >>> from . import FILES
        >>> pipe(conf={'url': FILES[6]}).next()['mileage']
        u'7213'
    """
    return parser(*args, **kwargs)
