# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.geolocate
~~~~~~~~~~~~~~~~~~~~~~
Provides functions for obtaining the geo location of an ip address, street
address, currency code, or lat/lon coordinates.

Examples:
    basic usage::

        >>> from riko.modules.geolocate import pipe
        >>>
        >>> address = '123 Bakersville St., London'
        >>> geolocate = next(pipe({'content': address}))['geolocate']
        >>> geolocate['country'] == 'United States'
        True


Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from builtins import *  # noqa pylint: disable=unused-import
from . import processor
from riko.utils import cast


OPTS = {'ftype': 'text', 'field': 'content'}
DEFAULTS = {'type': 'street_address'}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(address, objconf, skip=False, **kwargs):
    """ Parses the pipe content

    Args:
        address (str): The address to lookup
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: exchangerate)
        stream (dict): The original item

    Returns:
        Tuple(dict, bool): Tuple of (item, skip)

    Examples:
        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {'content': 'GBP'}
        >>> objconf = Objectify({'type': 'currency'})
        >>> kwargs = {'stream': item, 'assign': 'content'}
        >>> country = 'United Kingdom'
        >>> parser(item['content'], objconf, **kwargs)['country'] == country
        True
    """
    if skip:
        location = kwargs['stream']
    else:
        location = cast(address, 'location', loc_type=objconf.type)

    return location


# @processor(DEFAULTS, isasync=True, **OPTS)
# def async_pipe(*args, **kwargs):
#     """A processor module that asynchronously performs basic arithmetic, such
#     as addition and subtraction.

#     Args:
#         item (dict): The entry to process
#         kwargs (dict): The keyword arguments passed to the wrapper

#     Kwargs:
#         conf (dict): The pipe configuration. May contain the key 'type'.

#             type (str): The type of geolocation to perform. Must be one of
#                 'coordinates', 'street_address', 'ip_address', or 'currency'
#                 (default: 'street_address').

#         assign (str): Attribute to assign parsed content (default: geolocate)
#         field (str): Item attribute from which to obtain the first address to
#             operate on (default: 'content')

#     Returns:
#         Deferred: twisted.internet.defer.Deferred item with formatted currency

#     Examples:
#         >>> from riko.bado import react
#         >>> from riko.bado.mock import FakeReactor
#         >>>
#         >>> def run(reactor):
#         ...     callback = lambda x: print(next(x)['geolocate']['country'])
#         ...     conf = {'type': 'currency'}
#         ...     d = async_pipe({'content': 'GBP'}, conf=conf)
#         ...     return d.addCallbacks(callback, logger.error)
#         >>>
#         >>> try:
#         ...     react(run, _reactor=FakeReactor())
#         ... except SystemExit:
#         ...     pass
#         ...
#         United Kingdom
#     """
#     return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A processor module that performs basic arithmetic, such as addition and
    subtraction.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'type'.

            type (str): The type of geolocation to perform. Must be one of
                'coordinates', 'street_address', 'ip_address', or 'currency'
                (default: 'street_address').

        assign (str): Attribute to assign parsed content (default: geolocate)
        field (str): Item attribute from which to obtain the first address to
            operate on (default: 'content')

    Returns:
        dict: an item with math result

    Examples:
        >>> conf = {'type': 'currency'}
        >>> geolocate = next(pipe({'content': 'INR'}, conf=conf))['geolocate']
        >>> geolocate['country'] == 'India'
        True
        >>> address = '123 Bakersville St., London'
        >>> kwargs = {'field': 'address', 'assign': 'result'}
        >>> geolocate = next(pipe({'address': address}, **kwargs))['result']
        >>> geolocate['country'] == 'United States'
        True
    """
    return parser(*args, **kwargs)
