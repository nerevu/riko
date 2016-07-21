# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.csv
~~~~~~~~~~~~~~~~
Provides functions for fetching csv files.

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.modules.csv import pipe
        >>>
        >>> url = get_path('spreadsheet.csv')
        >>> next(pipe(conf={'url': url}))['mileage'] == '7213'
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from builtins import *
from six.moves.urllib.request import urlopen
from meza.io import read_csv

from . import processor
from riko.lib import utils
from riko.bado import coroutine, return_value, io

OPTS = {'ftype': 'none'}
DEFAULTS = {
    'delimiter': ',', 'quotechar': '"', 'encoding': 'utf-8', 'skip_rows': 0,
    'sanitize': True, 'dedupe': True, 'col_names': None, 'has_header': True}

logger = gogo.Gogo(__name__, monolog=True).logger


@coroutine
def async_parser(_, objconf, skip, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        Tuple(Iter[dict], bool): Tuple of (stream, skip)

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from riko.lib.utils import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x[0])['mileage'])
        ...     url = get_path('spreadsheet.csv')
        ...     conf = {'url': url, 'sanitize': True, 'skip_rows': 0}
        ...     objconf = Objectify(conf)
        ...     d = async_parser(None, objconf, False, stream={})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        7213
    """
    if skip:
        stream = kwargs['stream']
    else:
        url = utils.get_abspath(objconf.url)
        response = yield io.async_url_open(url)
        first_row, custom_header = objconf.skip_rows, objconf.col_names
        renamed = {'first_row': first_row, 'custom_header': custom_header}
        rkwargs = utils.combine_dicts(objconf, renamed)
        stream = read_csv(response, **rkwargs)

    result = (stream, skip)
    return_value(result)


def parser(_, objconf, skip, **kwargs):
    """ Parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content

    Returns:
        Tuple(Iter[dict], bool): Tuple of (stream, skip)

    Examples:
        >>> from riko import get_path
        >>> from riko.lib.utils import Objectify
        >>>
        >>> url = get_path('spreadsheet.csv')
        >>> conf = {'url': url, 'sanitize': True, 'skip_rows': 0}
        >>> objconf = Objectify(conf)
        >>> result, skip = parser(None, objconf, False, stream={})
        >>> next(result)['mileage'] == '7213'
        True
    """
    if skip:
        stream = kwargs['stream']
    else:
        url = utils.get_abspath(objconf.url)
        first_row, custom_header = objconf.skip_rows, objconf.col_names
        renamed = {'first_row': first_row, 'custom_header': custom_header}
        response = urlopen(url)
        encoding = utils.get_response_encoding(response, objconf.encoding)
        rkwargs = utils.combine_dicts(objconf, renamed)
        rkwargs['encoding'] = encoding
        stream = read_csv(response, **rkwargs)

    return stream, skip


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
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
        dict: twisted.internet.defer.Deferred item

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['mileage'])
        ...     d = async_pipe(conf={'url': get_path('spreadsheet.csv')})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        7213
    """
    return async_parser(*args, **kwargs)


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
        dict: item

    Examples:
        >>> from riko import get_path
        >>> url = get_path('spreadsheet.csv')
        >>> next(pipe(conf={'url': url}))['mileage'] == '7213'
        True
    """
    return parser(*args, **kwargs)
