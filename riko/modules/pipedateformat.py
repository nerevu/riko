# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipedateformat
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for formatting dates.

A wide range of format specifiers can be used to create the output text string.
The specifiers all begin with a percent sign followed by a single character.

Here are a few specifiers and how they each format the date/time February 12th,
2008 at 8:45 P.M.

    Specifier                   Formatted Date
    -------------------------   -------------------------------
    %m-%d-%Y                    02-12-2008
    %A, %b %d, %y at %I:%M %p   Tuesday, Feb 12, 08 at 08:45 PM
    %D 	                        02/12/08
    %R 	                        20:45
    %B 	                        February

Examples:
    basic usage::

        >>> from riko.modules.pipedateformat import pipe
        >>> from datetime import date
        >>> next(pipe({'date': date(2015, 5, 4)}))['dateformat']
        '05/04/2015 00:00:00'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from time import strftime

from builtins import *

from . import processor
from riko.lib.log import Logger

OPTS = {'field': 'date', 'ftype': 'date'}
DEFAULTS = {'format': '%m/%d/%Y %H:%M:%S'}
logger = Logger(__name__).logger


def parser(date, objconf, skip, **kwargs):
    """ Obtains the user input

    Args:
        date (dict): Must have key 'date' with a date-like object value
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content

    Returns:
        Tuple(dict, bool): Tuple of (the formatted date, skip)

    Examples:
        >>> from datetime import date
        >>> from riko.lib.utils import Objectify
        >>>
        >>> objconf = Objectify({'format': '%m/%d/%Y'})
        >>> parser({'date': date(2015, 5, 4)}, objconf, False)[0]
        '05/04/2015'
    """
    timetuple = date['date'].timetuple()
    parsed = kwargs['feed'] if skip else strftime(objconf.format, timetuple)
    return parsed, skip


@processor(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A processor module that asynchronously formats a date.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'format',
            'assign', or 'field'.

            format (str): Format string passed to time.strftime (default:
                '%m/%d/%Y %H:%M:%S', i.e., '02/12/2008 20:45:00')

            assign (str): Attribute to assign parsed content (default:
                dateformat)

            field (str): Item attribute from which to obtain the string to be
                formatted (default: 'date')

    Returns:
        Deferred: twisted.internet.defer.Deferred item with formatted date

    Examples:
        >>> from datetime import date
        >>> from twisted.internet.task import react
        >>> from riko.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['dateformat'])
        ...     d = asyncPipe({'date': date(2015, 5, 4)})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        05/04/2015 00:00:00
    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A processor module that formats a date.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'format',
            'assign', or 'field'.

            format (str): Format string passed to time.strftime (default:
                '%m/%d/%Y %H:%M:%S', i.e., '02/12/2008 20:45:00')

        assign (str): Attribute to assign parsed content (default:
            dateformat)

        field (str): Item attribute from which to obtain the string to be
            formatted (default: 'date')

    Returns:
        dict: an item with formatted date string

    Examples:
        >>> from datetime import date
        >>> item = {'date': date(2015, 5, 4)}
        >>> next(pipe(item))['dateformat']
        '05/04/2015 00:00:00'
        >>> next(pipe(item, conf={'format': '%Y'}))['dateformat']
        '2015'
        >>> next(pipe({'date': '05/04/2015'}))['dateformat']
        '05/04/2015 00:00:00'
    """
    return parser(*args, **kwargs)
