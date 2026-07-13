# vim: sw=4:ts=4:expandtab
"""
Provides utility classes and functions
"""

import dataclasses
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from html.entities import name2codepoint
from html.parser import HTMLParser
from io import BytesIO, StringIO, TextIOBase
from itertools import chain
from json import JSONDecodeError, loads
from time import struct_time
from typing import (
    TYPE_CHECKING,
    Literal,
    TypeAlias,
    Union,
    cast,
    overload,
)
from urllib.error import URLError
from xml.sax import SAXParseException  # noqa: S406

import feedparser
import pygogo as gogo
from ijson import IncompleteJSONError, items
from requests.structures import CaseInsensitiveDict

from riko import Objectify, listize
from riko.bado.io import NamedTextIOWrapper
from riko.dotdict import DotDict, is_sentinal, is_type_value
from riko.types.general import ComplexArg, ItemArg, SkipFunc, SkipIf
from riko.types.modules import AnyModuleConf, ConfValues, Skip
from riko.types.values import (
    BasicArg,
    ComplexMapping,
    ComplexSequence,
    IntermediateValue,
    RSSParseResult,
    StrictDate,
)
from riko.utils import Fetch, truncate_content

try:
    from lxml import etree, html  # type: ignore[import-untyped]
except ImportError:
    xml_parser = "ElementTree"
    html5parser = None

    import xml.etree.ElementTree as etree  # noqa: N813, S405
    from xml.etree.ElementTree import ElementTree  # noqa: S405

    import html5lib as html
else:
    ElementTree = None
    xml_parser = "lxml"
    from lxml.html import html5parser

try:
    import speedparser3 as speedparser
except ImportError:
    rss_parser = "feedparser"
    speedparser = None
else:
    rss_parser = "speedparser"

rssparser = speedparser or feedparser

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element as nativeElement
    from xml.etree.ElementTree import ElementTree as nativeElementTree

    from lxml.etree import Element as lxmlElement
    from lxml.etree import ElementTree as lxmlElementTree

AnyElementTree: TypeAlias = Union["nativeElementTree", "lxmlElementTree"]
AnyElement: TypeAlias = Union["nativeElement", "lxmlElement"]
Stringy: TypeAlias = Union[str, "StringySequence", "StringyMapping"]
StringyMapping: TypeAlias = Mapping[str, Stringy]
StringySequence: TypeAlias = Sequence[Stringy]

logger = gogo.Gogo(__name__, verbose=False, monolog=True).logger
logger.debug(f"{xml_parser=}")
logger.debug(f"{rss_parser=}")

ESCAPE = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;"}

SKIP_SWITCH: dict[str, Callable[[str, str], bool]] = {
    "contains": lambda text, value: text.lower() in value.lower(),
    "intersection": lambda text, value: bool(set(text).intersection(value)),
    "re.search": lambda text, value: re.search(text, value, re.IGNORECASE) is not None,
}


class LinkParser(HTMLParser):
    def __init__(
        self,
        *args,
        external_only=True,
        strict=True,
        rss_only=False,
        link_type: str | Iterable[str] | None = None,
        **kwargs,
    ):
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

    def keyfunc(self, entry):
        # sort according to the order of self.link_type
        count = len(self.link_type)
        enumerated = enumerate(self.link_type)
        pos = (i for i, t in enumerated if entry.get("type", "").endswith(t))
        return next(pos, count)

    def reset(self):
        HTMLParser.reset(self)
        self.entry = iter(())
        self.data = StringIO()

    def handle_starttag(self, tag: str, attrs: Sequence[tuple[str, str | None]]):
        entry = dict(attrs)
        link = entry.get("href")
        _type = entry.get("type", "")
        type_match = any(_type.endswith(t) for t in self.link_type)

        if link and not self.strict:
            type_match = type_match or any(link.endswith(t) for t in self.link_type)

        source_match = link and not (self.external_only and link.startswith("/"))

        if source_match and (type_match or not self.link_type):
            entry["link"] = link
            entry["tag"] = tag
            self.entry = chain(self.entry, [entry])

    def handle_data(self, data: str):
        self.data.write(f"{data}\n")


def get_text(html: str, convert_charrefs=False):
    try:
        parser = LinkParser(convert_charrefs=convert_charrefs)
    except TypeError:
        parser = LinkParser()

    parser.feed(html)
    return parser.data.getvalue()


# The overloads are so I can call parse_rss(**kwargs) with Pyright complaining.
# https://stackoverflow.com/q/79673094
@overload
def parse_rss(url: str, **kwargs: BasicArg) -> RSSParseResult: ...  # noqa: E704
@overload
def parse_rss(**kwargs: BasicArg) -> RSSParseResult: ...  # noqa: E704
def parse_rss(url: BasicArg = "", **kwargs: BasicArg) -> RSSParseResult:  # noqa: E302
    parsed: RSSParseResult = {"entries": []}

    try:
        f = Fetch(str(url), **kwargs)
    except URLError:
        # url is an xml string
        f, content, url = None, url, "content"
    else:
        content = f.read() if f.file else ""

    try:
        parsed = cast(RSSParseResult, rssparser.parse(content))
    finally:
        if f:
            f.close()

    bozo = parsed.get("bozo")
    entry_count = len(parsed.get("entries", []))

    if bozo is False and not entry_count:
        logger.warning(f"Parsed {url} successfully but no entries were found.")
    elif (bozo is False) or (entry_count > 3):
        pass
    elif bozo_exception := parsed.get("bozo_exception"):
        if isinstance(bozo_exception, SAXParseException):
            msg = bozo_exception.getMessage()
            logger.warning(f"Error parsing {url}: {msg}")
        else:
            msg = str(bozo_exception)
            logger.error(f"Error parsing {url}: {msg}")

        logger.warning(f"Content: {truncate_content(content)}")

    return parsed


def extract_namespace(tree: AnyElementTree) -> str | None:
    """
    Extracts the XML namespace URI from an element's tag.

    Args:
        tree (AnyElementTree): An element whose tag may contain a Clark-notation
            namespace, e.g. ``{http://example.com/ns}root``.

    Returns:
        str | None: The namespace URI, or ``None`` if the tag has no namespace.

    Examples:
        >>> from xml.etree.ElementTree import fromstring
        >>> tree = fromstring('<root xmlns="http://example.com/ns"/>')
        >>> extract_namespace(tree)
        'http://example.com/ns'
        >>> extract_namespace(fromstring('<root/>'))

    """
    tag = getattr(tree, "tag", None) or ""

    if not isinstance(tag, str):  # lxml uses QName objects sometimes
        tag = str(tag)

    if "{" in tag and "}" in tag:
        namespace = tag[tag.find("{") + 1 : tag.find("}")]
    else:
        namespace = None

    return namespace


def verify_pos(tree: AnyElementTree, pos: int, *tags: str) -> int:
    """
    Adjusts *pos* when *tree* IS the element at ``tags[pos]``.

    Descendant-search methods such as ``findall`` and ``getElementsByTagName``
    do not match *self*, so the position must be incremented when the root
    element is already the one described at that level of the path.
    Namespace prefixes (Clark notation ``{uri}localname``) are stripped before
    the comparison.

    Args:
        tree (AnyElementTree): The root element to inspect.
        pos (int): Current position in *tags*.
        *tags (str): Ordered tag names derived from the XPath expression.

    Returns:
        int: ``pos + 1`` if the local tag of *tree* equals ``tags[pos]``,
            otherwise *pos* unchanged.

    Examples:
        >>> from xml.etree.ElementTree import fromstring
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
    tree: AnyElementTree,
    path="/",
    pos: int | None = None,
    namespace: str | None = None,
    ns_prefix="ns",
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
        tree (AnyElementTree): The root element to search.
        path (str): An XPath-like expression. A leading ``/`` indicates an
            absolute path (sets initial *pos* to 1). Defaults to ``"/"``.
        pos (int | None): Starting index into the tag list. ``None`` triggers
            automatic detection via :func:`verify_pos`.
        namespace (str | None): Namespace URI for prefixed searches.
            Auto-detected from *tree* when ``None``.
        ns_prefix (str): Prefix token used in namespace-qualified path
            segments. Defaults to ``"ns"``.

    Yields:
        AnyElement: Each matched element.

    Examples:
        >>> from xml.etree.ElementTree import fromstring
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

    ns_path = "/".join(f"{ns_prefix}:{tag}" for tag in tags[pos:]) if namespace else ""
    namespaces = {ns_prefix: namespace}

    try:
        if namespace:
            elements = tree.xpath(  # type: ignore[attr-defined]
                ns_path, namespaces=namespaces
            )
        else:
            elements = tree.xpath(path)  # type: ignore[attr-defined]
    except AttributeError:
        if namespace:
            elements = tree.findall(f".//{ns_path}", namespaces=namespaces)
        else:
            elements = tree.findall(".//" + "/".join(tags[pos:]))

        yield from elements
    else:
        yield from elements


@overload
def xml2etree(  # noqa: E704
    f: str | BytesIO | StringIO | NamedTextIOWrapper | TextIOBase,
    xml: Literal[True],
    html5: bool = ...,
) -> AnyElementTree: ...
@overload  # noqa: E302
def xml2etree(  # noqa: E704
    f: str | BytesIO | StringIO | NamedTextIOWrapper | TextIOBase,
    xml: Literal[False],
    html5: Literal[True],
) -> AnyElementTree: ...
@overload  # noqa: E302
def xml2etree(  # noqa: E704
    f: str | BytesIO | StringIO | NamedTextIOWrapper | TextIOBase,
    xml: Literal[False],
    html5: Literal[False] = ...,
) -> "nativeElementTree": ...
def xml2etree(  # noqa: E302
    f: str | BytesIO | StringIO | NamedTextIOWrapper | TextIOBase,
    xml: bool = True,
    html5: bool = False,
) -> AnyElementTree | None:
    if xml:
        element_tree = etree.parse(f)  # noqa: S314
    elif html5 and html5parser:
        element_tree = html5parser.parse(f)
    elif xml_parser == "lxml":
        element_tree = html.parse(f)
    else:
        if html5 and not html5parser:
            logger.warning("lxml parser not found. Using html5lib instead.")

        # html5lib's parser returns an Element, so we must convert it into an
        # ElementTree
        element_tree = ElementTree(html.parse(f))

    return element_tree


def _make_content(
    i: StringyMapping,
    value: Stringy | None = None,
    tag="content",
    append=True,
    strip=False,
) -> StringyMapping:
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


def etree2dict(element: AnyElement) -> Stringy:
    """Convert an element tree into a dict imitating how Yahoo Pipes does it."""
    i: StringyMapping = dict(element.items())
    content = _make_content(i, element.text, strip=True)
    i.update(content)

    for child in element:
        tag = child.tag.split("}", 1)[-1]
        value = etree2dict(child)
        content = _make_content(i, value, tag)
        i.update(content)

    if element.text and not set(i).difference(["content"]):
        # element is leaf node and doesn't have attributes
        result = i["content"]
    else:
        result = i

    return result


def any2dict(
    content: NamedTextIOWrapper
    | TextIOBase
    | Stringy
    | IntermediateValue
    | DotDict
    | ComplexSequence,
    ext: str | None = "xml",
    html5=False,
    path: str | None = None,
) -> Iterator[
    Stringy | float | ComplexMapping | StrictDate | Sequence[ComplexArg]
]:
    path = path or ""

    if content is None:
        pass
    elif isinstance(content, DotDict):
        yield content.asdict()
    elif isinstance(content, (dict, CaseInsensitiveDict, Mapping)):
        yield content
    elif isinstance(content, list):
        for item in content:
            if item is not None:
                yield item
    elif ext and ext in {"xml", "html"}:
        xml = ext == "xml"
        root = xml2etree(content, xml, html5).getroot()

        if path:
            replaced = "/".join(path.split("."))

            for tree in xpath(root, replaced):
                value = etree2dict(tree)
                yield from any2dict(value, ext=None)
        else:
            yield etree2dict(root)
    elif ext == "json":
        if isinstance(content, str):
            try:
                json = loads(content)
            except JSONDecodeError as e:
                logger.error(e)
            else:
                value = DotDict(json).get(path, "")
                yield from any2dict(value, ext=None)
        else:
            objects = items(content, f"{path}.item")

            try:
                yield next(objects)
            except IncompleteJSONError as e:
                logger.error(e)
                content.seek(0)
                objects = items(content, path)

                try:
                    yield next(objects)
                except IncompleteJSONError as e:
                    logger.error(e)
                    logger.warning("Loading file into memory")
                    content.seek(0)
                    yield from any2dict(content.read(), ext="json", path=path)
                else:
                    yield from objects
            else:
                yield from objects
    elif ext:
        raise TypeError(f"Invalid file type: '{ext}'")
    elif isinstance(content, str):
        yield {"content": content}
    else:
        print(f"{content=}, {ext=}, {html5=}, {path=}")
        raise TypeError("No file type provided!")


def parse_conf(
    item: ItemArg = None, conf: AnyModuleConf | ConfValues | None = None, **kwargs
) -> ComplexArg:
    """
    Examples
    --------
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

    """
    kw = Objectify(kwargs)
    parsed = kw.default

    if is_dataclass(conf) and not isinstance(conf, type):
        conf = asdict(conf)

    if isinstance(conf, Mapping):
        dd_conf = DotDict(conf)

        if subkey := dd_conf.get("subkey"):
            dd_item = DotDict(item) if isinstance(item, Mapping) else DotDict()
            parsed = dd_item.get(cast(str, subkey), **kwargs)
        elif is_sentinal(dd_conf):
            parsed = dd_conf.get(**kwargs)
        elif is_type_value(dd_conf):
            parsed = cast(DotDict, dd_conf).get()
        else:
            parsed = {
                k.lower(): parse_conf(item, cast(ConfValues, v), **kwargs)
                for k, v in conf.items()
            }
    elif isinstance(conf, (str, struct_time)):
        parsed = conf
    elif isinstance(conf, Sequence):
        parsed = [parse_conf(item, c, **kwargs) for c in conf]
    elif conf is not None:
        parsed = conf

    return parsed


def get_skip(item: ItemArg, skip_if: SkipIf | None = None, **_) -> bool:
    """
    Determine whether or not to skip an item

    Args:
        item (dict): The entry to process
        skip_if (func or Iter[dict]): The skipping criteria

    Returns:
        bool: whether or not to skip

    Examples:
        >>> item = {'content': 'Some content'}
        >>> get_skip(item, lambda x: x['content'] == 'Some content')
        True
        >>> get_skip(item)
        False
        >>> get_skip(item, {'field': 'content'})
        False
        >>> bool(get_skip(item, {'field': 'content', 'include': True}))
        True
        >>> get_skip(item, {'field': 'content', 'text': 'some'})
        True
        >>> get_skip(item, {'field': 'content', 'text': 'some', 'include': True})
        False
        >>> get_skip(item, {'field': 'content', 'text': 'other'})
        False
        >>> get_skip(item, {'field': 'content', 'text': 'other', 'include': True})
        True

    """
    item = item or {}
    skip = False

    for __skip in listize(skip_if):
        _skip = cast(SkipFunc | Skip, __skip)

        if callable(_skip):
            skip = _skip(item)
        elif isinstance(item, Mapping):
            _skip = cast(Skip, _skip)
            field = _skip["field"]
            value = str(item.get(field, ""))

            if text := str(_skip.get("text")):
                op = str(_skip.get("op", "contains"))
                match = not SKIP_SWITCH[op](text, value)
                skip = match if _skip.get("include") else not match
            else:
                skip = bool(value) if _skip.get("include") else not value

        if skip:
            break

    return skip


def get_field(item: ItemArg = None, field="", **kwargs) -> ComplexArg:
    value = item

    if field and isinstance(item, Mapping):
        try:
            value = item.get(field, **kwargs)
        except TypeError:
            value = item.get(field)

    return value


def text2entity(text: str) -> str:
    """Convert HTML/XML special chars to entity references"""
    return ESCAPE.get(text, text)


def entity2text(entitydef: str) -> str:
    """
    Convert an HTML entity reference into unicode.
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
