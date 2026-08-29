# vim: sw=4:ts=4:expandtab
"""
Builds a url from its parts.

Allows pipelines to dynamically inject pieces (stock ticker, search term, page number,
etc.) into a url.

Examples:
    Basic usage::

        >>> from riko.modules.urlbuilder import pipe
        >>>
        >>> conf = {
        ...     "base": "http://finance.yahoo.com",
        ...     "path": ["rss", "headline"],
        ...     "param": {"key": "s", "value": "gm"},
        ... }
        >>> next(pipe(conf=conf))
        'http://finance.yahoo.com/rss/headline?s=gm'

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

import re
from collections.abc import Mapping, Sequence
from logging import Logger
from typing import Any
from urllib.parse import urlencode, urljoin

import pygogo as gogo

from riko._strutils import INVALID_FILECHAR_PATTERN
from riko.cast import BasicCastType
from riko.modules._prepare import require_conf
from riko.types._configs import UrlBuilderObjconf
from riko.types._options import Defaults, Opts
from riko.types._streams import Item
from riko.types.modules import ObjconfParam

from . import processor

OPTS: Opts = {"ftype": BasicCastType.NONE, "extract": "param", "listize": True}
DEFAULTS: Defaults = {"param": {}}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    _: Item, param: Sequence[ObjconfParam], objconf: UrlBuilderObjconf, **kwargs: object
) -> str:
    """
    Assembles a url from the configured parts.

    Args:
        _: The item. Unused.
        param: The parsed query parameters.
        objconf: The pipe configuration, containing `base`, `path` and `ext`.

    Returns:
        The url.

    Raises:
        TypeError: If ``conf`` has no ``base`` key.

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> param = {"key": "s", "value": "gm"}
        >>> conf = {
        ...     "base": "http://finance.yahoo.com",
        ...     "path": ["rss", "headline"],
        ...     "param": param,
        ... }
        >>> parser({}, [Objectify(param)], Objectify(conf))
        'http://finance.yahoo.com/rss/headline?s=gm'

    """
    if isinstance(objconf.path, str):
        paths = [objconf.path]
    elif isinstance(objconf.path, Mapping):
        logger.error(f"Path should be a string or list of strings, not {objconf.path}")
        paths = []
    elif objconf.path:
        paths = objconf.path
    else:
        paths = []

    encoded = urlencode([(p.key, p.value) for p in param if p.key])
    base: str = require_conf(objconf, "base", "urlbuilder")
    joined = urljoin(base, "/".join(paths))
    stream = f"{joined}?{encoded}" if encoded else joined

    if objconf.ext:
        substituted = re.sub(INVALID_FILECHAR_PATTERN, "_", stream)
        stream = f"{substituted}.{objconf.ext}"

    return stream


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> str:
    """
    Asynchronously builds a url from its parts.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, supplying values.

        conf (dict): The pipe configuration. Every value is either a literal or
            a ``{"subkey": ...}`` reference reading it from ``item``.

            base (str): The scheme and server name. Required.

            path (str | list[str]): The resource path. A list is joined with slashes
                (default: None).

            param (dict | list[dict]): The query parameters (default: none).

                key (str): The parameter name.
                value (str): The parameter value.

            ext (str): Extension to append, which also rewrites the url as a
                filename for offline use (default: None).

        context (Context): the execution context

    Kwargs:
        assign (str): Field the url is assigned to. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit the url directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<url>`` when ``emit`` is True (default)
        - ``{<assign>: <url>}`` when ``emit`` is False and no item given
        - merged ``{Item, <assign>: <url>}`` when ``emit`` is False and item is
          given

    Raises:
        TypeError: If ``conf`` has no ``base`` key.

    Notes:
        A parameter without a ``key`` is skipped.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     conf = {
        ...         "base": "http://finance.yahoo.com",
        ...         "path": ["rss", "headline"],
        ...         "param": {"key": "s", "value": "gm"},
        ...     }
        ...     result = await async_pipe(conf=conf)
        ...     print(next(result))
        >>>
        >>> run(main)
        http://finance.yahoo.com/rss/headline?s=gm

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> str:
    """
    Builds a url from its parts.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, supplying values.

        conf (dict): The pipe configuration. Every value is either a literal or
            a ``{"subkey": ...}`` reference reading it from ``item``.

            base (str): The scheme and server name. Required.

            path (str | list[str]): The resource path. A list is joined with slashes
                (default: None).

            param (dict | list[dict]): The query parameters (default: none).

                key (str): The parameter name.
                value (str): The parameter value.

            ext (str): Extension to append, which also rewrites the url as a
                filename for offline use (default: None).

        context (Context): the execution context

    Kwargs:
        assign (str): Field the url is assigned to. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit the url directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<url>`` when ``emit`` is True (default)
        - ``{<assign>: <url>}`` when ``emit`` is False and no item given
        - merged ``{Item, <assign>: <url>}`` when ``emit`` is False and item is
          given

    Raises:
        TypeError: If ``conf`` has no ``base`` key.

    Notes:
        A parameter without a ``key`` is skipped.

    Examples:
        >>> base = "http://finance.yahoo.com"
        >>> path = ["rss", "headline"]
        >>> conf = {
        ...     "base": base,
        ...     "path": ["rss", "headline"],
        ...     "param": {"key": "s", "value": "gm"},
        ... }
        >>> next(pipe(conf=conf))
        'http://finance.yahoo.com/rss/headline?s=gm'
        >>> next(pipe(conf={"base": base, "path": path, "param": {"key": "s"}}))
        'http://finance.yahoo.com/rss/headline?s=None'
        >>> next(pipe(conf={"base": base, "path": path, "param": {"value": "gm"}}))
        'http://finance.yahoo.com/rss/headline'
        >>> next(pipe(conf={"base": base, "path": "rss/headline"}))
        'http://finance.yahoo.com/rss/headline'
        >>> next(pipe(conf={"base": base, "path": "rss", "ext": "xml"}))
        'http___finance.yahoo.com_rss.xml'

    """
    return parser(*args, **kwargs)
