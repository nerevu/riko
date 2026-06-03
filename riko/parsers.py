# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.parsers
~~~~~~~~~~~~
Provides utility classes and functions
"""
from itertools import chain
from json import JSONDecodeError, loads
import re

from io import BytesIO, StringIO, TextIOBase
from html.entities import name2codepoint
from html.parser import HTMLParser
from time import struct_time
from typing import TYPE_CHECKING, Callable, Iterable, Iterator, Literal, Mapping, Optional, Sequence, TypeAlias, Union, cast, overload
from urllib.error import URLError

import feedparser
import pygogo as gogo

from riko import Objectify
from riko.dotdict import DotDict, is_sentinal, is_type_value
from riko.types.general import ComplexArg, BasicArg, ItemArg, Skip
from riko.utils import fetch
from riko import listize
from ijson import IncompleteJSONError, items

try:
    from lxml import html, etree
except ImportError:
    html5parser = None
    import html5lib as html

    try:
        import xml.etree.cElementTree as etree
    except ImportError:
        xml_parser = "ElementTree"
        import xml.etree.ElementTree as etree
        from xml.etree.ElementTree import ElementTree
    else:
        xml_parser = "cElementTree"
        from xml.etree.cElementTree import ElementTree
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
    from xml.etree.ElementTree import ElementTree as pElementTree
    from xml.etree.cElementTree import ElementTree as cElementTree
    from lxml.etree import ElementTree as lElementTree

    from xml.etree.ElementTree import Element as pElement
    from xml.etree.cElementTree import Element as cElement
    from lxml.etree import Element as lElement

    from speedparser3.feedparsercompat import FeedParserDict as SpeedParserDict
    from feedparser import FeedParserDict

StdElementTree: TypeAlias = Union["pElementTree", "cElementTree"]
AnyElementTree: TypeAlias = Union[StdElementTree, "lElementTree"]
AnyElement: TypeAlias = Union["pElement", "cElement", "lElement"]
Stringy: TypeAlias = Union[str, "StringySequence", "StringyMapping"]
StringyMapping: TypeAlias = Mapping[str, Stringy]
StringySequence: TypeAlias = Sequence[Stringy]

logger = gogo.Gogo(__name__, verbose=False, monolog=True).logger
logger.debug(f"{xml_parser=}")
logger.debug(f"{rss_parser=}")

NAMESPACES = {
    "owl": "http://www.w3.org/2002/07/owl#",
    "xhtml": "http://www.w3.org/1999/xhtml",
}

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
        link_type: Optional[str | Iterable[str]] = None,
        **kwargs
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
            self.link_type = tuple([])

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


def parse_rss(url="", **kwargs) -> Union[dict[str, list], "FeedParserDict", "SpeedParserDict"]:
    parsed = {"parsed": []}

    try:
        f = fetch(url, **kwargs)
    except URLError:
        # url is an xml string
        f, content, url = None, url, "content"
    else:
        content = f.read() if f.file else ""

    try:
        parsed = rssparser.parse(content)
    finally:
        if f:
            f.close()

    if bozo_exception := parsed.get("bozo_exception"):
        msg = bozo_exception.getMessage()
        logger.error(f"Error parsing {url}: {msg}")
        logger.error(f"Content: {content}")

    return parsed


def xpath(
    tree: AnyElementTree,
    path="/",
    pos=0,
    namespace: Optional[str] = None
) -> Iterator[AnyElement]:
    if not namespace:
        tag = str(getattr(tree, 'tag', '') or str(tree).split(" ")[1])

        if '{' in tag and '}' in tag:
            ns = tag[tag.find('{') + 1:tag.find('}')]
            ns_iter = (name for name in NAMESPACES if name in ns)
            namespace = next(ns_iter, ns)

    ns_path = '/'.join(f'ns:{p}' for p in path.split('/') if p) if namespace else path

    try:
        if namespace:
            elements = tree.xpath(ns_path, namespaces={'ns': namespace})
        else:
            elements = tree.xpath(path)
    except AttributeError:
        stripped = path.lstrip("/")
        tags = stripped.split("/") if stripped else []

        try:
            # TODO: consider replacing with twisted.words.xish.xpath
            elements = tree.getElementsByTagName(tags[pos]) if tags else [tree]
        except AttributeError:
            prefix = (f"/{namespace}:") if namespace else "/"
            match = f"./{prefix}{prefix.join(tags[1:])}"
            elements = tree.findall(match, NAMESPACES)
        except IndexError:
            elements = [tree]
        else:
            for element in elements:
                return xpath(element, path, pos + 1)

    return iter(elements)


@overload
def xml2etree(f: str | BytesIO | StringIO | TextIOBase, xml: Literal[True], html5: bool = ...) -> AnyElementTree:  # noqa: E501
    ...
@overload  # noqa: E302
def xml2etree(f: str | BytesIO | StringIO | TextIOBase, xml: Literal[False], html5: Literal[True]) -> AnyElementTree:
    ...
@overload  # noqa: E302
def xml2etree(f: str | BytesIO | StringIO | TextIOBase, xml: Literal[False], html5: Literal[False] = ...) -> StdElementTree:
    ...
def xml2etree(  # noqa: E302
    f: str | BytesIO | StringIO | TextIOBase,
    xml: bool = True,
    html5: bool = False,
) -> Optional[AnyElementTree]:
    if xml:
        element_tree = etree.parse(f)
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
    value: Optional[Stringy] = None,
    tag="content",
    append=True,
    strip=False
) -> StringyMapping:
    content: Stringy = i.get(tag, "")

    if value and isinstance(value, str) and strip:
        value = value.strip()

    if content and value and append:
        content = list(listize(content))
        content.append(value)
    elif content and value and isinstance(content, str) and isinstance(value, str):
        content = "".join([content, value])
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
    f: StringIO | TextIOBase | Stringy,
    ext: Optional[str] = "xml",
    html5=False,
    path: Optional[str] = None
) -> Iterator[Stringy]:
    path = path or ""

    if isinstance(f, (int, Mapping, struct_time)):
        yield f
    elif isinstance(f, Sequence) and not isinstance(f, str):
        yield from f
    elif ext and ext in {"xml", "html"}:
        xml = ext == "xml"
        root = xml2etree(f, xml, html5).getroot()

        if path:
            replaced = "/".join(path.split("."))

            for tree in xpath(root, replaced):
                value = etree2dict(tree)
                yield from any2dict(value, ext=None)
        else:
            yield etree2dict(root)
    elif ext == "json":
        if isinstance(f, str):
            try:
                json = loads(f)
            except JSONDecodeError as e:
                logger.error(e)
            else:
                value = DotDict(json).get(path, "")
                yield from any2dict(value, ext=None)
        else:
            objects = items(f, f"{path}.item")

            try:
                yield next(objects)
            except IncompleteJSONError as e:
                logger.error(e)
                f.seek(0)
                objects = items(f, path)

                try:
                    yield next(objects)
                except IncompleteJSONError as e:
                    logger.error(e)
                    logger.warning("Loading file into memory")
                    f.seek(0)
                    yield from any2dict(f.read(), ext="json", path=path)
                else:
                    yield from objects
            else:
                yield from objects
    elif ext:
        raise TypeError(f"Invalid file type: '{ext}'")
    elif isinstance(f, str):
        yield f
    else:
        raise TypeError("No file type provided!")


def parse_conf(
    item: Optional[ItemArg] = None,
    conf: Optional[BasicArg] = None,
    **kwargs
) -> ComplexArg:
    """
    Examples
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

    if isinstance(item, Mapping):
        dd_item = DotDict(item)
    elif item:
        dd_item = None
    else:
        dd_item = DotDict()

    if isinstance(conf, Mapping):
        dd_conf = DotDict(conf)

        if dd_item is not None and (subkey := dd_conf.get("subkey")):
            parsed = dd_item.get(cast(str, subkey), **kwargs)
        elif is_sentinal(dd_conf):
            parsed = dd_conf.get(**kwargs)
        elif is_type_value(dd_conf):
            parsed = cast(DotDict, dd_conf).get()
        else:
            parsed = {
                k.lower(): parse_conf(item, v, **kwargs)
                for k, v in conf.items()
            }
    elif isinstance(conf, (str, int)):
        parsed = conf
    elif isinstance(conf, Sequence):
        parsed = [parse_conf(item, c, **kwargs) for c in conf]

    return parsed


def get_skip(
    item: ItemArg,
    skip_if: Optional[Callable[[ItemArg], bool] | Skip | Iterable[Callable[[ItemArg], bool]] | Iterable[Skip]] = None,
    **_
) -> bool:
    """Determine whether or not to skip an item

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

    for _skip in listize(skip_if):
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


def get_field(item: Optional[ItemArg] = None, field="", **kwargs) -> ComplexArg:
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
    """Convert an HTML entity reference into unicode.
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
