# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.parsers
~~~~~~~~~~~~
Provides utility classes and functions
"""
from itertools import chain
import re

from io import StringIO
from html.entities import name2codepoint
from html.parser import HTMLParser
from typing import Any, Iterable, Mapping, Optional, Sequence
from urllib.error import URLError

import feedparser
import pygogo as gogo

from riko.dotdict import DotDict
from riko.types import Item
from riko.utils import fetch
from meza.fntools import Objectify, remove_keys, listize
from meza.process import merge
from meza.compat import decode
from ijson import items

logger = gogo.Gogo(__name__, verbose=False, monolog=True).logger

try:
    from lxml import html, etree
except ImportError:
    html5parser = None
    import html5lib as html

    try:
        import xml.etree.cElementTree as etree
    except ImportError:
        logger.debug("xml parser: ElementTree")
        import xml.etree.ElementTree as etree
        from xml.etree.ElementTree import ElementTree
    else:
        logger.debug("xml parser: cElementTree")
        from xml.etree.cElementTree import ElementTree
else:
    ElementTree = None
    logger.debug("xml parser: lxml")
    from lxml.html import html5parser

try:
    import speedparser3 as speedparser
except ImportError:
    logger.debug("rss parser: feedparser")
    speedparser = None
else:
    logger.debug("rss parser: speedparser")

rssparser = speedparser or feedparser


NAMESPACES = {
    "owl": "http://www.w3.org/2002/07/owl#",
    "xhtml": "http://www.w3.org/1999/xhtml",
}

ESCAPE = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;"}

SKIP_SWITCH = {
    "contains": lambda text, value: text.lower() in value.lower(),
    "intersection": lambda text, value: set(text).intersection(value),
    "re.search": lambda text, value: re.search(text, value, re.IGNORECASE),
}


class LinkParser(HTMLParser):
    def __init__(
        self,
        *args,
        rss_only=False,
        link_type: Optional[str|Iterable[str]]=None,
        **kwargs
    ):
        if rss_only:
            self.link_type = ["rss+xml", "rdf+xml", "atom+xml", "text/xml", "xml"]
        elif isinstance(link_type, str):
            self.link_type = [link_type]
        elif link_type:
            self.link_type = list(link_type)
        else:
            self.link_type = None

        super().__init__(*args, **kwargs)

    def reset(self):
        HTMLParser.reset(self)
        self.entry = iter(())
        self.data = StringIO()

    def handle_starttag(self, tag, attrs):
        entry = dict(attrs)
        link = entry.get("href")
        _type = entry.get("type", "")
        type_match = (_type.endswith(t) for t in self.link_type)

        if link and (not self.link_type or next(type_match, None)):
            entry["link"] = link
            entry["tag"] = tag
            self.entry = chain(self.entry, [entry])

    def handle_data(self, data):
        self.data.write("%s\n" % decode(data))


def get_text(html, convert_charrefs=False):
    try:
        parser = LinkParser(convert_charrefs=convert_charrefs)
    except TypeError:
        parser = LinkParser()

    try:
        parser.feed(html)
    except TypeError:
        parser.feed(decode(html))

    return parser.data.getvalue()


def parse_rss(url="", **kwargs):
    try:
        f = fetch(decode(url), **kwargs)
    except (ValueError, URLError):
        parsed = rssparser.parse(url)
    else:
        content = f.read() if speedparser else f

        try:
            parsed = rssparser.parse(content)
        finally:
            f.close()

    return parsed


def xpath(tree, path="/", pos=0, namespace=None):
    try:
        elements = tree.xpath(path)
    except AttributeError:
        stripped = path.lstrip("/")
        tags = stripped.split("/") if stripped else []

        try:
            # TODO: consider replacing with twisted.words.xish.xpath
            elements = tree.getElementsByTagName(tags[pos]) if tags else [tree]
        except AttributeError:
            element_name = str(tree).split(" ")[1]

            if not namespace and {"{", "}"}.issubset(element_name):
                start, end = element_name.find("{") + 1, element_name.find("}")
                ns = element_name[start:end]
                ns_iter = (name for name in NAMESPACES if name in ns)
                namespace = next(ns_iter, namespace)

            prefix = ("/%s:" % namespace) if namespace else "/"
            match = "./%s%s" % (prefix, prefix.join(tags[1:]))
            elements = tree.findall(match, NAMESPACES)
        except IndexError:
            elements = [tree]
        else:
            for element in elements:
                return xpath(element, path, pos + 1)

    return iter(elements)


def xml2etree(f, xml=True, html5=False):
    if xml:
        element_tree = etree.parse(f)
    elif html5 and html5parser:
        element_tree = html5parser.parse(f)
    elif html5parser:
        element_tree = html.parse(f)
    elif ElementTree:
        # html5lib's parser returns an Element, so we must convert it into an
        # ElementTree
        element_tree = ElementTree(html.parse(f))
    else:
        logger.error("No suitable HTML parser found. Please install lxml or html5lib.")
        element_tree = None

    return element_tree


def _make_content(i, value=None, tag="content", append=True, strip=False):
    content = i.get(tag)

    try:
        value = value.strip() if value and strip else value
    except AttributeError:
        pass

    if content and value and append:
        content = listize(content)
        content.append(value)
    elif content and value:
        content = "".join([content, value])
    elif value:
        content = value

    return {tag: content} if content else {}


def etree2dict(element):
    """Convert an element tree into a dict imitating how Yahoo Pipes does it."""
    i = dict(element.items())
    i.update(_make_content(i, element.text, strip=True))

    for child in element:
        tag = child.tag
        # tag = child.tag.split("}", 1)[-1]
        value = etree2dict(child)
        i.update(_make_content(i, value, tag))

    if element.text and not set(i).difference(["content"]):
        # element is leaf node and doesn't have attributes
        i = i.get("content")

    return i


def any2dict(f, ext="xml", html5=False, path=None):
    path = path or ""

    if ext in {"xml", "html"}:
        xml = ext == "xml"
        root = xml2etree(f, xml, html5).getroot()
        replaced = "/".join(path.split("."))
        tree = next(xpath(root, replaced)) if replaced else root
        content = etree2dict(tree)
    elif ext == "json":
        content = next(items(f, path))
    else:
        raise TypeError("Invalid file type: '%s'" % ext)

    return content


def get_value(
    item: Item,
    subconf: Optional[Mapping[str, Any] | Sequence[Any]] = None,
    default=None,
    **kwargs
) -> Any:
    """
    param = {
        "key": {"type": "text", "value": "q"},
        "value": {"type": "text", "subkey": "title"}
    }

    item = {"title": "the title"}
    get_value(item, subconf=param, objectify=True)
    "the title"

    params = [
        {
            "key": {"type": "text", "value": "q"},
            "value": {"type": "text", "subkey": "title"}
        },
        {
            "key": {"type": "text", "value": "v"},
            "value": {"type": "text", "value": "1.0"}
        }
    ]

    get_value(item, subconf=param, objectify=True)
    [{"q": "the title"}, {"v": "1.0"}]
    """
    value = default
    dd_item = DotDict(item or {})

    if isinstance(subconf, Mapping):
        subconf = DotDict(subconf)

        if subvalue := subconf.get("subkey"):
            value = dd_item.get(subvalue, **kwargs)
        elif subconf:
            value = subconf.get(default=default, **kwargs)
    elif subconf is not None:
        value = subconf

    return value


def parse_conf(item: Item, conf=None, **kwargs):
    """
    conf = {
            "count": {"type": "text", "value": "all"},
            "assign": {"type": "text", "value": "url"},
            "BASE": {"type": "text", "value": "http://example.com"},
            "PARAM": [
                {
                    "key": {"type": "text", "value": "q"},
                    "value": {"type": "text", "subkey": "title"}
                },
                {
                    "key": {"type": "text", "value": "v"},
                    "value": {"type": "text", "value": "1.0"}
                }
            ]
        },
        "type": "urlbuilder"
    }

    item = {"title": "the title"}
    parse_conf(item, conf=conf, objectify=True)
    {
        "count": "all",
        "assign": "url",
        "base": "http://example.com",
        "param": [{"q": "the title"}, {"v": "1.0"}]
    }
    """

    kw = Objectify(kwargs, defaults={})

    if isinstance(conf, Mapping):
        conf = Objectify(conf)
        parsed = {k.lower(): get_value(item, v, **kwargs) for k, v in conf.items()}
        result = merge([kw.defaults, parsed])
        objectified = Objectify(result) if kw.objectify else result
    else:
        objectified = get_value(item, conf, **kwargs)

    return objectified


def get_skip(item, skip_if=None, **kwargs):
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

    for _skip in listize(skip_if):
        if callable(_skip):
            skip = _skip(item)
        elif _skip:
            value = item.get(_skip["field"], "")
            text = _skip.get("text")
            op = _skip.get("op", "contains")
            match = not SKIP_SWITCH[op](text, value) if text else value
            skip = match if _skip.get("include") else not match
        else:
            skip = False

        if skip:
            break

    return skip


def get_field(item: Item, field="", **kwargs) -> Any:
    try:
        value = item.get(field, **kwargs) if field else item
    except TypeError:
        value = item.get(field) if field else item

    return value


def get_with(item: Item, **kwargs) -> Any:
    loop_with = kwargs.pop('with', None)

    try:
        value = item.get(loop_with, **kwargs) if loop_with else item
    except TypeError:
        value = item.get(loop_with) if loop_with else item

    return value


def text2entity(text):
    """Convert HTML/XML special chars to entity references"""
    return ESCAPE.get(text, text)


def entity2text(entitydef):
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
