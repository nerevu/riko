# vim: sw=4:ts=4:expandtab
"""
Parses feeds and XML, HTML, and JSON documents.

Attributes:

    XML_PARSER: Hardened lxml parser (entity, DTD, and network access
        disabled), or ``None`` when lxml is unavailable.

    ESCAPE: XML/HTML special-character to entity-reference map.

"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from html.entities import name2codepoint
from html.parser import HTMLParser
from io import BytesIO, RawIOBase, StringIO
from itertools import chain
from json import JSONDecodeError, load, loads
from logging import Logger
from types import ModuleType
from typing import TYPE_CHECKING, Any, Union, cast

import feedparser
import pygogo as gogo

from riko.base._constants import STREAMING_THRESHOLD
from riko.coercion._sequences import listize
from riko.types._collections import RikoDict, Stringy, StringyDict
from riko.types._guards import is_mapping
from riko.types._io import FileLike
from riko.types._streams import Item, Stream

from ._dotdict import DotDict

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

    from lxml import html as lxmlhtml
    from lxml.etree import _Element as lxmlElement
    from lxml.etree import _ElementTree as lxmlElementTree

type AnyElementTree = (
    "nativeElementTree | lxmlElementTree | nativeElementTree[nativeElement[str]]"
)
type AnyElement = "nativeElement | lxmlElement"

logger: Logger = gogo.Gogo(__name__, verbose=False, monolog=True).logger
logger.debug(f"{IS_LXML=}")
logger.debug(f"{IS_FASTFEEDPARSER=}")

ESCAPE = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;"}


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
        type_ = entry.get("type") or ""
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
    Emits elements matching *path* from *tree* across multiple XML backends.

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
    Emits items parsed from ``content`` (XML/HTML/JSON, mapping, or list).

    ``path`` locates the list of items within a parsed document.

    """
    path = path or ""

    if isinstance(content, DotDict):
        yield content.asdict()
    elif is_mapping(content):
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

        if use_ijson and ijson:
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
