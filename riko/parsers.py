# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.parsers
~~~~~~~~~~~~
Provides utility classes and functions
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import re

from io import StringIO
from html.entities import name2codepoint
from html.parser import HTMLParser

try:
    from urllib.error import URLError
except ImportError:
    from six.moves.urllib_error import URLError

import pygogo as gogo

from builtins import *  # noqa pylint: disable=unused-import
from riko.utils import fetch
from meza.fntools import Objectify, remove_keys, listize
from meza.process import merge
from meza.compat import decode
from ijson import items

logger = gogo.Gogo(__name__, verbose=False, monolog=True).logger

try:
    from lxml import etree, html
except ImportError:
    try:
        import xml.etree.cElementTree as etree
    except ImportError:
        logger.debug('xml parser: ElementTree')
        import xml.etree.ElementTree as etree
        from xml.etree.ElementTree import ElementTree
    else:
        logger.debug('xml parser: cElementTree')
        from xml.etree.cElementTree import ElementTree

    import html5lib as html
    html5parser = None
else:
    logger.debug('xml parser: lxml')
    from lxml.html import html5parser

try:
    import speedparser
except ImportError:
    import feedparser
    logger.debug('rss parser: feedparser')
    speedparser = None
else:
    logger.debug('rss parser: speedparser')

rssparser = speedparser or feedparser


NAMESPACES = {
    'owl': 'http://www.w3.org/2002/07/owl#',
    'xhtml': 'http://www.w3.org/1999/xhtml'}

ESCAPE = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;'}

SKIP_SWITCH = {
    'contains': lambda text, value: text.lower() in value.lower(),
    'intersection': lambda text, value: set(text).intersection(value),
    're.search': lambda text, value: re.search(text, value),
}


class LinkParser(HTMLParser):
    def reset(self):
        HTMLParser.reset(self)
        self.data = StringIO()

    def handle_data(self, data):
        self.data.write('%s\n' % decode(data))


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


def parse_rss(url=None, **kwargs):
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


def xpath(tree, path='/', pos=0, namespace=None):
    try:
        elements = tree.xpath(path)
    except AttributeError:
        stripped = path.lstrip('/')
        tags = stripped.split('/') if stripped else []

        try:
            # TODO: consider replacing with twisted.words.xish.xpath
            elements = tree.getElementsByTagName(tags[pos]) if tags else [tree]
        except AttributeError:
            element_name = str(tree).split(' ')[1]

            if not namespace and {'{', '}'}.issubset(element_name):
                start, end = element_name.find('{') + 1, element_name.find('}')
                ns = element_name[start:end]
                ns_iter = (name for name in NAMESPACES if name in ns)
                namespace = next(ns_iter, namespace)

            prefix = ('/%s:' % namespace) if namespace else '/'
            match = './%s%s' % (prefix, prefix.join(tags[1:]))
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
    else:
        # html5lib's parser returns an Element, so we must convert it into an
        # ElementTree
        element_tree = ElementTree(html.parse(f))

    return element_tree


def _make_content(i, value=None, tag='content', append=True, strip=False):
    content = i.get(tag)

    try:
        value = value.strip() if value and strip else value
    except AttributeError:
        pass

    if content and value and append:
        content = listize(content)
        content.append(value)
    elif content and value:
        content = ''.join([content, value])
    elif value:
        content = value

    return {tag: content} if content else {}


def etree2dict(element):
    """Convert an element tree into a dict imitating how Yahoo Pipes does it.
    """
    i = dict(element.items())
    i.update(_make_content(i, element.text, strip=True))

    for child in element:
        tag = child.tag
        value = etree2dict(child)
        i.update(_make_content(i, value, tag))

    if element.text and not set(i).difference(['content']):
        # element is leaf node and doesn't have attributes
        i = i.get('content')

    return i


def any2dict(f, ext='xml', html5=False, path=None):
    path = path or ''

    if ext in {'xml', 'html'}:
        xml = ext == 'xml'
        root = xml2etree(f, xml, html5).getroot()
        replaced = '/'.join(path.split('.'))
        tree = next(xpath(root, replaced)) if replaced else root
        content = etree2dict(tree)
    elif ext == 'json':
        content = next(items(f, path))
    else:
        raise TypeError("Invalid file type: '%s'" % ext)

    return content


def get_value(item, conf=None, force=False, default=None, **kwargs):
    item = item or {}

    try:
        value = item.get(conf['subkey'], **kwargs)
    except KeyError:
        if conf and not (hasattr(conf, 'delete') or force):
            raise TypeError('conf must be of type DotDict')
        elif force:
            value = conf
        elif conf:
            value = conf.get(**kwargs)
        else:
            value = default
    except (TypeError, AttributeError):
        # conf is already set to a value so use it or the default
        value = default if conf is None else conf
    except (ValueError):
        # error converting subkey value with OPS['func'] so use the default
        value = default

    return value


def parse_conf(item, **kwargs):
    kw = Objectify(kwargs, defaults={}, conf={})
    # TODO: fix so .items() returns a DotDict instance
    # parsed = {k: get_value(item, v) for k, v in kw.conf.items()}
    sentinel = {'subkey', 'value', 'terminal'}
    not_dict = not hasattr(kw.conf, 'keys')

    if not_dict or (len(kw.conf) == 1 and sentinel.intersection(kw.conf)):
        objectified = get_value(item, **kwargs)
    else:
        no_conf = remove_keys(kwargs, 'conf')
        parsed = {k: get_value(item, kw.conf[k], **no_conf) for k in kw.conf}
        result = merge([kw.defaults, parsed])
        objectified = Objectify(result) if kw.objectify else result

    return objectified


def get_skip(item, skip_if=None, **kwargs):
    item = item or {}

    if callable(skip_if):
        skip = skip_if(item)
    elif skip_if:
        skips = listize(skip_if)

        for _skip in skips:
            value = item.get(_skip['field'], '')
            text = _skip.get('text')
            op = _skip.get('op', 'contains')
            match = SKIP_SWITCH[op](text, value) if text else value
            skip = match if _skip.get('include') else not match

            if skip:
                break
    else:
        skip = False

    return skip


def get_field(item, field=None, **kwargs):
    return item.get(field, **kwargs) if field else item


def text2entity(text):
    """Convert HTML/XML special chars to entity references
    """
    return ESCAPE.get(text, text)


def entity2text(entitydef):
    """Convert an HTML entity reference into unicode.
    http://stackoverflow.com/a/58125/408556
    """
    if entitydef.startswith('&#x'):
        cp = int(entitydef[3:-1], 16)
    elif entitydef.startswith('&#'):
        cp = int(entitydef[2:-1])
    elif entitydef.startswith('&'):
        cp = name2codepoint[entitydef[1:-1]]
    else:
        logger.debug(entitydef)
        cp = None

    return chr(cp) if cp else entitydef
