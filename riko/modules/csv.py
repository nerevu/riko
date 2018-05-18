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

from builtins import *  # noqa pylint: disable=unused-import
from meza.io import read_csv
from meza.process import merge

from . import processor
from riko import ENCODING
from riko.bado import coroutine, return_value, io
from riko.utils import fetch, auto_close, get_abspath

OPTS = {'ftype': 'none'}
DEFAULTS = {
    'delimiter': ',', 'quotechar': '"', 'encoding': ENCODING, 'skip_rows': 0,
    'sanitize': True, 'dedupe': True, 'col_names': None, 'has_header': True}

logger = gogo.Gogo(__name__, monolog=True).logger


@coroutine
def async_parser(_, objconf, skip=False, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from meza.fntools import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['mileage'])
        ...     url = get_path('spreadsheet.csv')
        ...     conf = {
        ...         'url': url, 'sanitize': True, 'skip_rows': 0,
        ...         'encoding': ENCODING}
        ...     objconf = Objectify(conf)
        ...     d = async_parser(None, objconf, stream={})
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
        url = get_abspath(objconf.url)
        r = yield io.async_url_open(url)
        first_row, custom_header = objconf.skip_rows, objconf.col_names
        renamed = {'first_row': first_row, 'custom_header': custom_header}
        rkwargs = merge([objconf, renamed])
        stream = auto_close(read_csv(r, **rkwargs), r)

    return_value(stream)


def parser(_, objconf, skip=False, **kwargs):
    """ Parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> url = get_path('spreadsheet.csv')
        >>> conf = {
        ...     'url': url, 'sanitize': True, 'skip_rows': 0,
        ...     'encoding': ENCODING}
        >>> objconf = Objectify(conf)
        >>> result = parser(None, objconf, stream={})
        >>> next(result)['mileage'] == '7213'
        True
    """
    if skip:
        stream = kwargs['stream']
    else:
        first_row, custom_header = objconf.skip_rows, objconf.col_names
        renamed = {'first_row': first_row, 'custom_header': custom_header}

        f = fetch(decode=True, **objconf)
        rkwargs = merge([objconf, renamed])
        stream = auto_close(read_csv(f, **rkwargs), f)

    return stream


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
        ...     d.addCallbacks(callback, logger.error)
        ...     return d.addCallback(lambda _: d.close())
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
