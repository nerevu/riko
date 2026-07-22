# vim: sw=4:ts=4:expandtab
"""
Provides functions for obtaining the geo location of an ip address, street
address, currency code, or lat/lon coordinates.

Examples:
    basic usage::

        >>> from riko.modules.geolocate import pipe
        >>>
        >>> address = '123 Bakersville St., USA'
        >>> geolocate = next(pipe({'content': address}))
        >>> geolocate['country']
        'United States'


Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

import pygogo as gogo

from riko.cast import BasicCastType, CastType, cast
from riko.types.configs import GeolocateObjconf
from riko.types.general import Defaults, Extraction, Opts
from riko.types.values import AnyLocation

from . import processor

OPTS: Opts = {"ftype": BasicCastType.TEXT, "field": "content"}
DEFAULTS: Defaults = {"type": "street_address"}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    address: str, extraction: Extraction, objconf: GeolocateObjconf, **kwargs
) -> AnyLocation:
    """
    Parses the pipe content

    Args:
        address (str): The address to lookup
        objconf (obj): The pipe configuration (an Objectify instance)
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: geolocate)
        stream (dict): The original item

    Examples:
        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {'content': 'GBP'}
        >>> objconf = Objectify({'type': 'currency'})
        >>> kwargs = {'stream': item, 'assign': 'content'}
        >>> parser(item['content'], None, objconf, **kwargs)['country']
        'United Kingdom'

    """
    return cast(address, CastType.LOCATION, loc_type=objconf.type)


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> AnyLocation:
    """
    A processor module that asynchronously obtains the geo location of an ip address, street
    address, currency code, or lat/lon coordinates.

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
        Awaitable: item with formatted location

    Examples:
        >>> from riko.bado import run
        >>>
        >>> async def main():
        ...     conf = {'type': 'currency'}
        ...     result = await async_pipe({'content': 'GBP'}, conf=conf)
        ...     print(next(result)['country'])
        >>>
        >>> run(main)
        United Kingdom

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> AnyLocation:
    """
    A processor module that obtains the geo location of an ip address, street
    address, currency code, or lat/lon coordinates.

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
        dict: an item with formatted location

    Examples:
        >>> conf = {'type': 'currency'}
        >>> geolocate = next(pipe({'content': 'INR'}, conf=conf))
        >>> geolocate['country']
        'India'
        >>> address = '123 Bakersville St., USA'
        >>> kwargs = {'field': 'address', 'emit': False, 'assign': 'result'}
        >>> geolocate = next(pipe({'address': address}, **kwargs))['result']
        >>> geolocate['country']
        'United States'

    """
    return parser(*args, **kwargs)
