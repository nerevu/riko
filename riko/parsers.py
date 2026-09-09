# vim: sw=4:ts=4:expandtab
"""
riko.parsers
~~~~~~~~~~~~

Parses feeds, XML/HTML documents, and pipe configurations.

Attributes:
    XML_PARSER: Hardened lxml parser (entity, DTD, and network access
        disabled), or ``None`` when lxml is unavailable.

    SKIP_SWITCH: Named text predicates backing ``get_skip``.

    ESCAPE: XML/HTML special-character to entity-reference map.

"""

import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from html.entities import name2codepoint
from html.parser import HTMLParser
from io import BytesIO, RawIOBase, StringIO
from itertools import chain
from json import JSONDecodeError, load, loads
from logging import Logger
from time import struct_time
from types import ModuleType
from typing import TYPE_CHECKING, Any, Union, cast, overload
from urllib.error import URLError
from xml.sax import SAXParseException  # noqa: S406

import feedparser
import pygogo as gogo
from requests.structures import CaseInsensitiveDict

from riko._io import STREAMING_THRESHOLD, Fetch
from riko._iterutils import listize
from riko._rssutils import truncate_content
from riko._serialize import repr_cache
from riko.dotdict import DotDict, is_sentinel, is_type_value
from riko.types._collections import BasicArg, RikoDict, Stringy, StringyDict
from riko.types._guards import is_mapping
from riko.types._io import FileLike
from riko.types._options import SkipIf
from riko.types._rss import ParserRSSEntry
from riko.types._scalars import AnyStr
from riko.types._streams import Item, ItemOrValue, Stream

try:
    from lxml import etree, html
except ImportError:
    html5parser: ModuleType | None = None

    import xml.etree.ElementTree as etree  # noqa: N813, S405
    from xml.etree.ElementTree import ElementTree  # noqa: S405

    import html5lib as html

    IS_LXML: bool = False
    XML_PARSER: Any = None
else:
    from xml.etree.ElementTree import ElementTree  # noqa: S405

    from lxml.html import html5parser

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

    from _typeshed import DataclassInstance
    from lxml import html as lxmlhtml
    from lxml.etree import _Element as lxmlElement
    from lxml.etree import _ElementTree as lxmlElementTree

type AnyElementTree = (
    "nativeElementTree" | "lxmlElementTree" | "nativeElementTree[nativeElement[str]]"
)
type AnyElement = "nativeElement" | "lxmlElement"

logger: Logger = gogo.Gogo(__name__, verbose=False, monolog=True).logger
logger.debug(f"{IS_LXML=}")
logger.debug(f"{IS_FASTFEEDPARSER=}")

ESCAPE = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;"}

SKIP_SWITCH: dict[str, Callable[[str, str], bool]] = {
    "contains": lambda text, value: text.lower() in value.lower(),
    "intersection": lambda text, value: bool(set(text).intersection(value)),
    "search": lambda text, value: re.search(text, value, re.IGNORECASE) is not None,
}


class LinkParser(HTMLParser):
    strict: bool
    external_only: bool
    link_type: tuple[str, ...]
    entry: Iterator[Mapping[str, str | None]]
    data: StringIO

    def __init__(
        self,
        *args: Any,
        external_only: bool = True,
        strict: bool = True,
        rss_only: bool = False,
        link_type: str | Iterable[str] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.strict = strict
        self.external_only = external_only

        if rss_only:
            self.link_type = ("rss+xml", "atom+xml", "rdf+xml", "text/xml", "xml")
        elif isinstance(link_type, str):
            self.link_type = (link_type,)
        elif link_type:
            self.link_type = tuple(link_type)
        else:
            self.link_type = ()

    def keyfunc(self, entry: Item) -> int:
        # sort according to the order of self.link_type
        count = len(self.link_type)
        enumerated = enumerate(self.link_type)
        pos = (i for i, t in enumerated if str(entry.get("type", "")).endswith(t))
        return next(pos, count)

    def reset(self) -> None:
        HTMLParser.reset(self)
        self.entry = iter(())
        self.data = StringIO()

    def handle_starttag(
        self, tag: str, attrs: Sequence[tuple[str, str | None]]
    ) -> None:
        entry = dict(attrs)
        link = entry.get("href")
        type_ = entry.get("type", "")
        type_match = any(type_.endswith(t) for t in self.link_type)

        if link and not self.strict:
            type_match = type_match or any(link.endswith(t) for t in self.link_type)

        source_match = link and not (self.external_only and link.startswith("/"))

        if source_match and (type_match or not self.link_type):
            entry["link"] = link
            entry["tag"] = tag
            self.entry = chain(self.entry, [entry])

    def handle_data(self, data: str) -> None:
        self.data.write(f"{data}\n")


def get_text(html: str, convert_charrefs: bool = False) -> str:
    """Extracts the concatenated text of ``html`` via ``LinkParser``."""
    try:
        parser = LinkParser(convert_charrefs=convert_charrefs)
    except TypeError:
        parser = LinkParser()

    parser.feed(html)
    return parser.data.getvalue()


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
    """Fetches (or reads) and parses an RSS/Atom feed into its entries."""
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
        parsed = rss_parser.parse(source)  # pyright: ignore[reportArgumentType]
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


def extract_namespace(tree: AnyElementTree | AnyElement) -> str | None:
    """
    Extracts the XML namespace URI from an element's tag.

    Args:
        tree: An element whose tag may contain a Clark-notation namespace, e.g.
            ``{http://example.com/ns}root``.

    Returns:
        The namespace URI, or ``None`` if the tag has no namespace.

    Examples:
        >>> from xml.etree.ElementTree import fromstring
        >>>
        >>> tree = fromstring('<root xmlns="http://example.com/ns"/>')
        >>> extract_namespace(tree)
        'http://example.com/ns'
        >>> extract_namespace(fromstring('<root/>'))

    """
    tag = str(getattr(tree, "tag", None) or "")

    if "{" in tag and "}" in tag:
        namespace = tag[tag.find("{") + 1 : tag.find("}")]
    else:
        namespace = None

    return namespace


def verify_pos(tree: AnyElementTree | AnyElement, pos: int, *tags: str) -> int:
    """
    Adjusts *pos* when *tree* IS the element at ``tags[pos]``.

    Descendant-search methods such as ``findall`` and ``getElementsByTagName``
    do not match *self*, so the position must be incremented when the root
    element is already the one described at that level of the path.
    Namespace prefixes (Clark notation ``{uri}localname``) are stripped before
    the comparison.

    Args:
        tree: The root element to inspect.
        pos: Current position in *tags*.
        *tags: Ordered tag names derived from the XPath expression.

    Returns:
        ``pos + 1`` if the local tag of *tree* equals ``tags[pos]``, otherwise *pos*
        unchanged.

    Examples:
        >>> from xml.etree.ElementTree import fromstring
        >>>
        >>> rss = fromstring('<rss/>')
        >>> verify_pos(rss, 0, 'rss', 'channel', 'item')
        1
        >>> verify_pos(rss, 1, 'rss', 'channel', 'item')
        1
        >>> channel = fromstring('<channel/>')
        >>> verify_pos(channel, 1, 'rss', 'channel', 'item')
        2
        >>> ns_rss = fromstring('<rss xmlns="http://purl.org/rss/1.0/"/>')
        >>> verify_pos(ns_rss, 0, 'rss', 'channel')
        1

    """
    tag = getattr(tree, "tag", None) or ""

    if not isinstance(tag, str):
        tag = str(tag)

    tree_local = tag.split("}")[-1] if "}" in tag else tag

    if tags and pos < len(tags) and tree_local == tags[pos]:
        pos += 1

    return pos


def xpath(
    tree: AnyElementTree | AnyElement,
    path: str = "/",
    pos: int | None = None,
    namespace: str | None = None,
    ns_prefix: str = "ns",
) -> Iterator[AnyElement]:
    """
    Yields elements matching *path* from *tree* across multiple XML backends.

    Three backends are tried in order:

    1. **lxml** — ``tree.xpath(...)`` with an optional namespace mapping.
    2. **ElementTree** — ``tree.findall(".//...")`` (stdlib fallback).

    When *pos* is ``None`` (the default) the function calls
    :func:`verify_pos` to detect whether *tree* is already the element at
    the first level of *path*, incrementing *pos* automatically so
    descendant searches start at the correct level.

    Args:
        tree: The root element to search.

        path: An XPath-like expression. A leading ``/`` indicates an absolute
            path (sets initial *pos* to 1).

        pos: Starting index into the tag list. ``None`` triggers automatic
            detection via :func:`verify_pos`.

        namespace: Namespace URI for prefixed searches. Auto-detected from
            *tree* when ``None``.

        ns_prefix: Prefix token used in namespace-qualified path segments.

    Yields:
        AnyElement: Each matched element.

    Examples:
        >>> from xml.etree.ElementTree import fromstring
        >>>
        >>> xml = '<rss><channel><item>a</item><item>b</item></channel></rss>'
        >>> tree = fromstring(xml)

        Absolute path from the rss root:

        >>> [el.text for el in xpath(tree, '/rss/channel/item')]
        ['a', 'b']

        Relative path when tree is the channel element:

        >>> channel = tree.find('channel')
        >>> [el.text for el in xpath(channel, 'item')]
        ['a', 'b']

        Relative path when tree IS the top-level tag in the path:

        >>> [el.text for el in xpath(tree, 'rss/channel/item')]
        ['a', 'b']

        With a namespace:

        >>> NS = 'http://purl.org/rss/1.0/'
        >>> xml_ns = f'<rss xmlns="{NS}"><channel><item>x</item></channel></rss>'
        >>> tree_ns = fromstring(xml_ns)
        >>> [el.text for el in xpath(tree_ns, '/rss/channel/item')]
        ['x']

    """
    namespace = namespace or extract_namespace(tree) or ""
    auto_pos = pos is None

    if auto_pos:
        pos = 1 if path.startswith("/") else 0

    stripped = path.strip("/")
    tags = stripped.split("/") if stripped else []

    if auto_pos:
        pos = verify_pos(tree, pos, *tags)

    namespaces = {ns_prefix: namespace}
    ns_path = "/".join(f"{ns_prefix}:{tag}" for tag in tags[pos:]) if namespace else ""

    if hasattr(tree, "xpath"):
        _xpath = cast(Union["lxmlElementTree", "lxmlElement"], tree).xpath
        elements = _xpath(ns_path, namespaces=namespaces) if namespace else _xpath(path)
    elif namespace:
        elements = tree.findall(f".//{ns_path}", namespaces=namespaces)
    else:
        elements = tree.findall(".//" + "/".join(tags[pos:]))

    yield from elements


def xml2etree(  # noqa: E302
    f: str | FileLike, xml: bool = True, html5: bool = False
) -> AnyElementTree:
    """
    Parses XML/HTML into an ElementTree. External XML is parsed with a hardened
    policy: entity resolution, DTD loading, and network access are disabled to
    guard against XXE and entity-expansion attacks.

    Examples:
        >>> from io import StringIO
        >>>
        >>> xxe = (
        ...     '<?xml version="1.0"?>'
        ...     '<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        ...     '<r>&x;</r>')
        >>> try:
        ...     root = xml2etree(StringIO(xxe), xml=True).getroot()
        ...     'root' not in (root.text or '')
        ... except Exception:
        ...     True
        True

    """
    if xml:
        element_tree = etree.parse(f, XML_PARSER)  # noqa: S314
    elif html5 and html5parser:
        element_tree = cast("lxmlElementTree", html5parser.parse(f))
    elif IS_LXML:
        element_tree = cast("lxmlhtml", html).parse(f)
    else:
        if html5 and not html5parser:
            logger.warning("lxml parser not found. Using html5lib instead.")

        element = cast("nativeElement", html.parse(f))
        element_tree = cast("nativeElementTree", ElementTree(element))

    return element_tree


def _make_content(
    i: StringyDict,
    value: Stringy | None = None,
    tag="content",
    append=True,
    strip=False,
) -> StringyDict:
    content: Stringy = i.get(tag, "")

    if value and isinstance(value, str) and strip:
        value = value.strip()

    if content and value and append:
        content = list(listize(content))
        content.append(value)
    elif content and value and isinstance(content, str) and isinstance(value, str):
        content = f"{content}{value}"
    elif content and value:
        msg = f"got non-string content or value: ({type(content)=}), ({type(value)=})"
        msg += " Try again setting append=True."
        logger.warning(msg)
    elif value:
        content = value

    return {tag: content} if content else {}


def element2dict(element: AnyElement) -> StringyDict:
    """Converts an element tree into a dict imitating how Yahoo Pipes does it."""
    i: StringyDict = dict(element.items())
    text = element.text
    content = _make_content(i, text, strip=True)
    i.update(content)

    for child in element:
        tag = str(child.tag).split("}", 1)[-1]
        value = element2dict(child)
        content = _make_content(i, value, tag)
        i.update(content)

    if text and not set(i).difference(["content"]):
        # element is leaf node and doesn't have attributes
        result = cast(StringyDict, i["content"])
    else:
        result = i

    return result


def any2dict(
    content: FileLike | RikoDict | list[RikoDict],
    ext: str | None = "xml",
    html5: bool = False,
    path: str | None = None,
) -> Stream:
    """
    Yields items parsed from ``content`` (XML/HTML/JSON, mapping, or list).

    ``path`` locates the list of items within a parsed document.

    """
    path = path or ""

    if isinstance(content, DotDict):
        yield content.asdict()
    elif isinstance(content, (dict, CaseInsensitiveDict, Mapping)):
        yield content
    elif isinstance(content, list):
        for item in content:
            if item is not None:
                yield item
    elif ext and ext in {"xml", "html"}:
        if ext == "xml":
            root = xml2etree(content, xml=True, html5=html5).getroot()
        else:
            root = xml2etree(content, xml=False, html5=html5).getroot()

        if path and root is not None:
            replaced = "/".join(path.split("."))

            for element in xpath(root, replaced):
                value = element2dict(element)
                yield from any2dict(value, ext=None)
        elif root is not None:
            yield element2dict(root)
    elif ext == "json":
        if not IJSON_IS_NATIVE:
            use_ijson = False
        elif isinstance(content, BytesIO):
            size = content.seek(0, 2)
            content.seek(0)
            use_ijson = size >= STREAMING_THRESHOLD
        else:
            use_ijson = isinstance(content, RawIOBase)

        if use_ijson:
            if path and not path.endswith(".item"):
                prefix = f"{path}.item"
            else:
                prefix = path

            items = ijson.items(content, prefix, use_float=True)
            yield from cast(Stream, items)
        elif isinstance(content, str):
            try:
                json = loads(content)
            except JSONDecodeError as e:
                logger.error(e)
            else:
                value = DotDict(json).get(path, "")
                yield from any2dict(cast(list[RikoDict], value), ext=None)
        else:
            try:
                json_obj = load(content)
            except (JSONDecodeError, ValueError) as e:
                logger.error(e)
            else:
                value = DotDict(json_obj).get(path, "") if path else json_obj
                yield from any2dict(cast(RikoDict, value), ext=None)
    elif ext:
        raise TypeError(f"Invalid file type: '{ext}'")
    elif isinstance(content, str):
        yield {"content": content}
    else:
        print(f"{content=}, {ext=}, {html5=}, {path=}")
        raise TypeError("No file type provided!")


def _conf_is_dynamic_uncached(conf: object, **kwargs: object) -> bool:
    is_dynamic = False

    if isinstance(conf, Mapping):
        if "subkey" in conf or is_sentinel(conf, **kwargs):
            is_dynamic = True
        else:
            values = conf.values()
            is_dynamic = any(_conf_is_dynamic_uncached(v, **kwargs) for v in values)
    elif isinstance(conf, Sequence) and not isinstance(conf, str):
        is_dynamic = any(_conf_is_dynamic_uncached(c, **kwargs) for c in conf)

    return is_dynamic


@repr_cache
def _conf_is_dynamic_cached(conf: object, **kwargs: object) -> bool:
    return _conf_is_dynamic_uncached(conf, **kwargs)


def conf_is_dynamic(conf: object, memoize: bool = False, **kwargs: object) -> bool:
    """
    Whether ``conf`` holds a ``subkey`` or sentinel needing per-item parsing.

    Examples:
        >>> _conf_is_dynamic_cached.cache_clear()
        >>> conf_is_dynamic({'type': 'text', 'value': 'hello'}, True)
        False
        >>> conf_is_dynamic({'type': 'text', 'subkey': 'title'}, True)
        True
        >>> _ = conf_is_dynamic({'type': 'text', 'value': 'hello'}, True)
        >>> _conf_is_dynamic_cached.cache_info().hits
        1

    """
    func = _conf_is_dynamic_cached if memoize else _conf_is_dynamic_uncached
    return func(conf, **kwargs)


def _parse_conf_uncached[VT](
    item: Item | None = None,
    conf: VT | None = None,
    default: VT | None = None,
    **kwargs: VT,
) -> VT | None:
    parsed = default

    if is_dataclass(conf):
        d_conf: dict[str, VT] | VT | None = asdict(cast("DataclassInstance", conf))
    else:
        d_conf = conf

    dd_conf = DotDict.dictize(d_conf)

    if isinstance(dd_conf, DotDict):
        if subkey := dd_conf.get("subkey"):
            dd_item = DotDict.dictize(item) if item else DotDict()
            parsed = dd_item.get(cast(str, subkey), **kwargs)
        elif is_sentinel(dd_conf, **kwargs) or is_type_value(dd_conf):
            # parsed = next(gen_dict(dd_conf, key=None, default_key=None, **kwargs))
            parsed = cast(DotDict[VT], dd_conf).get()
        else:
            _parsed = {
                k: _parse_conf_uncached(item, v, **kwargs)
                for k, v in dd_conf.asdict(key=None, **kwargs).items()
            }
            parsed = cast(VT, _parsed)
    elif isinstance(dd_conf, (str, struct_time)):
        parsed = dd_conf
    elif isinstance(dd_conf, (list, tuple)):
        _parsed = [_parse_conf_uncached(item, c, **kwargs) for c in dd_conf]
        parsed = cast(VT, _parsed)
    elif dd_conf is not None:
        parsed = cast(VT, dd_conf)

    return parsed


@repr_cache
def _parse_conf_cached[VT](
    item: Item | None = None,
    conf: VT | None = None,
    default: VT | None = None,
    **kwargs: VT,
) -> VT | None:
    return _parse_conf_uncached(item, conf, default=default, **kwargs)


def parse_conf[VT](
    item: Item | None = None,
    conf: VT | None = None,
    default: VT | None = None,
    memoize: bool | None = None,
    **kwargs: VT,
) -> VT | None:
    """
    Resolves a pipe ``conf`` against an ``item`` by expanding subkeys and sentinels.

    Static confs are memoized by default. ``memoize`` forces the choice.

    Examples:
        >>> param = {
        ...     "key": {"type": "text", "value": "q"},
        ...     "value": {"type": "text", "subkey": "title"}
        ... }
        >>> params = [
        ...     param,
        ...     {
        ...         "key": {"type": "text", "value": "v"},
        ...         "value": {"type": "text", "value": "1.0"}
        ...     }
        ... ]
        >>> conf = {
        ...     "count": {"type": "text", "value": "all"},
        ...     "type": "urlbuilder",
        ...     "BASE": {"type": "text", "value": "http://example.com"},
        ...     "PARAM": params
        ... }
        >>> item = {"title": "the title"}
        >>> parsed = parse_conf(item, conf=conf, objectify=True)
        >>> parsed["count"], parsed["base"]
        ('all', 'http://example.com')
        >>> parsed["param"]
        [{'key': 'q', 'value': 'the title'}, {'key': 'v', 'value': '1.0'}]
        >>> conf = DotDict({"terminal": "attrs_1", "type": "text"})
        >>> conf.get(attrs_1=iter([{'content': 'baz'}]))
        {'content': 'baz'}
        >>> _parse_conf_cached.cache_clear()
        >>> parse_conf(conf={'type': 'text', 'value': 'hello'})
        'hello'
        >>> _parse_conf_cached.cache_info().hits
        0
        >>> _ = parse_conf(conf={'type': 'text', 'value': 'hello'})
        >>> _parse_conf_cached.cache_info().hits
        1
        >>> parse_conf(conf={'type': 'text', 'value': 'hello'}, memoize=False)
        'hello'
        >>> _parse_conf_cached.cache_info().hits
        1
        >>> _ = parse_conf(conf={'type': 'text', 'value': 'hello'}, memoize=True)
        >>> _parse_conf_cached.cache_info().hits
        2

    """
    if memoize is None:
        memoize = not conf_is_dynamic(conf, memoize=False, **kwargs)

    func = _parse_conf_cached if memoize else _parse_conf_uncached
    return func(item, conf, default=default, **kwargs)


def get_skip(item: ItemOrValue, skip_if: SkipIf | None = None, **_: object) -> bool:
    """
    Determines whether or not to skip an item.

    Args:
        item: The entry to process.
        skip_if: The skipping criteria.

    Returns:
        Whether or not to skip.

    Examples:
        >>> item = {"content": "Some content"}
        >>> get_skip(item, lambda x: x["content"] == "Some content")
        True
        >>> get_skip(item)
        False
        >>> get_skip(item, {"field": "content"})
        False
        >>> get_skip(item, {"field": "content", "text": None})
        False
        >>> get_skip(item, {"field": "content", "text": 0})
        False
        >>> get_skip(item, {"field": "content", "text": ""})
        True
        >>> get_skip({}, {"field": "content"})
        True
        >>> bool(get_skip(item, {"field": "content", "include": True}))
        True
        >>> get_skip(item, {"field": "content", "text": "some"})
        True
        >>> get_skip(item, {"field": "content", "text": "some", "include": True})
        False
        >>> get_skip(item, {"field": "content", "text": "other"})
        False
        >>> get_skip(item, {"field": "content", "text": "other", "include": True})
        True

    """
    item = item or {}
    skip = False

    if is_mapping(item):
        for _skip in listize(skip_if):
            if callable(_skip):
                skip = _skip(item)
            elif is_mapping(_skip) and (field := _skip["field"]):
                value = item.get(field)

                if (text := _skip.get("text")) is None:
                    skip = bool(value) if _skip.get("include") else not value
                elif value is None:
                    skip = not _skip.get("include")
                else:
                    op = str(_skip.get("op", "contains"))
                    match = SKIP_SWITCH[op](str(text), str(value))
                    skip = not match if _skip.get("include") else match

            if skip:
                break

    return skip


def get_field(
    item: ItemOrValue | None = None, field: str = "", **kwargs: ItemOrValue
) -> ItemOrValue:
    """Returns ``item[field]``, or ``item`` itself when no field is given."""
    if field and isinstance(item, DotDict):
        value = item.get(field, **kwargs)
    elif field and isinstance(item, dict):
        value = item.get(field)
    else:
        value = item

    return value


def text2entity(text: str) -> str:
    """Converts HTML/XML special chars to entity references."""
    return ESCAPE.get(text, text)


def entity2text(entitydef: str) -> str:
    """
    Converts an HTML entity reference into unicode.
    http://stackoverflow.com/a/58125/408556
    """
    if entitydef.startswith("&#x"):
        cp = int(entitydef[3:-1], 16)
    elif entitydef.startswith("&#"):
        cp = int(entitydef[2:-1])
    elif entitydef.startswith("&"):
        cp = name2codepoint[entitydef[1:-1]]
    else:
        logger.debug(entitydef)
        cp = None

    return chr(cp) if cp else entitydef
