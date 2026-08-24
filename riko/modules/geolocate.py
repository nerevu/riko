# vim: sw=4:ts=4:expandtab
"""
Resolves a currency code, street/ip address, or coordinates to a location.

Warning:
    Only ``type="currency"`` performs a real lookup. ``street_address`` and
    ``ip_address`` ignore their input and return fixed placeholder data, and
    ``coordinates`` echoes the supplied lat/lon but reports a placeholder
    country. See ``riko.cast.lookup_street_address`` and friends.

Examples:
    Basic usage::

        >>> from riko.modules.geolocate import pipe
        >>>
        >>> next(pipe({"content": "GBP"}, conf={"type": "currency"}))["country"]
        'United Kingdom'

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from logging import Logger
from typing import Any

import pygogo as gogo

from riko.cast import BasicCastType, CastType, cast_value
from riko.types.configs import GeolocateObjconf
from riko.types.general import Defaults, Extraction, Opts
from riko.types.values import AnyLocation

from . import processor

OPTS: Opts = {"ftype": BasicCastType.TEXT, "field": "content"}
DEFAULTS: Defaults = {"type": "street_address"}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    address: str, extraction: Extraction, objconf: GeolocateObjconf, **kwargs: object
) -> AnyLocation:
    """
    Resolves ``address`` to a location of the configured type.

    Args:
        address: The value to resolve — a currency code, street address, ip
            address, or ``"lat,lon"`` pair.

        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `type`.

    Returns:
        The resolved location. Only ``type="currency"`` consults real data.

    Raises:
        KeyError: If ``type`` is not a supported lookup.

    Examples:
        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {"content": "GBP"}
        >>> objconf = Objectify({"type": "currency"})
        >>> kwargs = {"stream": item, "assign": "content"}
        >>> parser(item["content"], None, objconf, **kwargs)["country"]
        'United Kingdom'

    """
    return cast_value(address, CastType.LOCATION, loc_type=objconf.type)


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> AnyLocation:
    """
    Asynchronously resolves an item field to a location.

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            type (str): The lookup to perform, one of "currency", "street_address",
                "ip_address", "coordinates" (default: "street_address").

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute holding the value to resolve
            (default: "content").

        assign (str): Field the location is assigned to. Ignored when ``emit``
            is True (default: "geolocate").

        emit (bool): Whether to emit the location in place of the item rather
            than assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <location>}`` when ``emit`` is False and
          item is given (default)
        - ``{<assign>: <location>}`` when ``emit`` is False and no item given
        - ``<location>`` when ``emit`` is True

    Raises:
        KeyError: If ``type`` is not a supported lookup.

    Notes:
        Only ``"currency"`` resolves real data; the other lookups return placeholder
        values.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     conf = {"type": "currency"}
        ...     result = await async_pipe({"content": "GBP"}, conf=conf)
        ...     print(next(result)["country"])
        >>>
        >>> run(main)
        United Kingdom

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> AnyLocation:
    """
    Resolves an item field to a location.

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            type (str): The lookup to perform, one of "currency", "street_address",
                "ip_address", "coordinates" (default: "street_address").

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute holding the value to resolve
            (default: "content").

        assign (str): Field the location is assigned to. Ignored when ``emit``
            is True (default: "geolocate").

        emit (bool): Whether to emit the location in place of the item rather
            than assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <location>}`` when ``emit`` is False and
          item is given (default)
        - ``{<assign>: <location>}`` when ``emit`` is False and no item given
        - ``<location>`` when ``emit`` is True

    Raises:
        KeyError: If ``type`` is not a supported lookup.

    Notes:
        Only ``"currency"`` resolves real data; the other lookups return placeholder
        values.

    Examples:
        >>> conf = {"type": "currency"}
        >>> geolocate = next(pipe({"content": "INR"}, conf=conf))
        >>> geolocate["country"]
        'India'
        >>> address = "123 Bakersville St., USA"
        >>> kwargs = {"field": "address", "emit": False, "assign": "result"}
        >>> geolocate = next(pipe({"address": address}, **kwargs))["result"]
        >>> geolocate["country"]
        'United States'

    """
    return parser(*args, **kwargs)
