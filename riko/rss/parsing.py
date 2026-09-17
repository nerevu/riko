"""
RSS and Atom feed parsing with optional accelerated parser backends.

Examples:

    >>> from riko.rss.parsing import parse_rss
    >>>
    >>> content = (
    ...     "<rss version='2.0'><channel><title>Example</title>"
    ...     "<item><title>First</title></item></channel></rss>"
    ... )
    >>> parse_rss(content=content)[0]["title"]
    'First'

Attributes:

    IS_LXML: Whether lxml is available for hardened XML parsing.
    XML_PARSER: Hardened lxml parser, or ``None`` without lxml.
    IS_FASTFEEDPARSER: Whether the optional fast feed parser is available.
    IJSON_IS_NATIVE: Whether ijson is using a native backend.

"""

from logging import Logger
from types import ModuleType
from typing import TYPE_CHECKING, Any, cast, overload
from urllib.error import URLError
from xml.sax import SAXParseException  # noqa: S406

import feedparser
import pygogo as gogo

from riko.base._strutils import truncate_content
from riko.io._sync import Fetch
from riko.types._collections import BasicArg
from riko.types._rss import ParserRSSEntry
from riko.types._scalars import AnyStr

try:
    from lxml import etree
except ImportError:
    html5parser: ModuleType | None = None

    import xml.etree.ElementTree as etree  # noqa: N813, S405

    IS_LXML: bool = False
    XML_PARSER: Any = None
else:
    IS_LXML: bool = True
    XML_PARSER = etree.XMLParser(  # noqa: S314
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
    )

try:
    import fastfeedparser
except ImportError:
    rss_parser: ModuleType = feedparser
    IS_FASTFEEDPARSER = False
else:
    rss_parser: ModuleType = fastfeedparser
    IS_FASTFEEDPARSER = True

try:
    import ijson
except ImportError:
    ijson = None
    IJSON_IS_NATIVE = False
else:
    IJSON_IS_NATIVE = getattr(ijson, "backend", "python") != "python"

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element as nativeElement
    from xml.etree.ElementTree import ElementTree as nativeElementTree

    from lxml.etree import _Element as lxmlElement
    from lxml.etree import _ElementTree as lxmlElementTree

type AnyElementTree = (
    "nativeElementTree | lxmlElementTree | nativeElementTree[nativeElement[str]]"
)
type AnyElement = "nativeElement | lxmlElement"

logger: Logger = gogo.Gogo(__name__, verbose=False, monolog=True).logger
logger.debug(f"{IS_LXML=}")
logger.debug(f"{IS_FASTFEEDPARSER=}")


# The overloads are so I can call parse_rss(**kwargs) with Pyright complaining.
# https://stackoverflow.com/q/79673094
@overload
def parse_rss(  # noqa: E704
    url: str, *, content: None = ..., **kwargs: BasicArg
) -> list[ParserRSSEntry]: ...
@overload  # noqa: E302
def parse_rss(  # noqa: E704
    *, content: AnyStr, **kwargs: BasicArg
) -> list[ParserRSSEntry]: ...
@overload
def parse_rss(**kwargs: Any) -> list[ParserRSSEntry]: ...  # noqa: E704
def parse_rss(  # noqa: E302
    url: BasicArg = "", *, content: AnyStr | None = None, **kwargs: BasicArg
) -> list[ParserRSSEntry]:
    """
    Fetches or reads an RSS/Atom feed and returns its parsed entries.

    Args:

        url: URL, path, or source string used when ``content`` is not supplied.
        content: Feed content to parse directly instead of fetching ``url``.
        **kwargs: Additional options forwarded to ``Fetch`` when reading ``url``.

    Returns:

        Parsed RSS/Atom entries in source order.

    Examples:

        >>> content = (
        ...     "<rss version='2.0'><channel><title>Example</title>"
        ...     "<item><title>First</title></item></channel></rss>"
        ... )
        >>> entries = parse_rss(content=content)
        >>> len(entries), entries[0]["title"]
        (1, 'First')

    """
    f = None

    if content is None:
        source_name = str(url)

        try:
            f = Fetch(source_name, binary=True, **kwargs)
        except URLError:
            source, source_name = source_name, "content"
        else:
            if f.file and IS_FASTFEEDPARSER:
                # fastfeedparser.parse takes str/bytes only (no file-like input)
                source = f.read()
            elif f.file:
                source = f.file  # feedparser reads the file object directly
            else:
                source = b""
    else:
        source, source_name = content, "content"

    try:
        parsed = rss_parser.parse(source)
    finally:
        if f:
            f.close()

    bozo = parsed.get("bozo")
    entry_count = len(parsed.entries)

    if bozo is False and not entry_count:
        logger.warning(f"Parsed {source_name} successfully but no entries were found.")
    elif (bozo is False) or (entry_count > 3):
        pass
    elif bozo_exception := parsed.get("bozo_exception"):
        if isinstance(bozo_exception, SAXParseException):
            msg = bozo_exception.getMessage()
            logger.warning(f"Error parsing {source_name}: {msg}")
        else:
            msg = str(bozo_exception)
            logger.error(f"Error parsing {source_name}: {msg}")

        logger.warning(f"Content: {truncate_content(source)}")

    return cast(list[ParserRSSEntry], parsed.entries)
