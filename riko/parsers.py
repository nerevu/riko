# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.utils
~~~~~~~~~~~~~~
Provides utility classes and functions
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import re
import sys
import itertools as it
import time
import fcntl

from math import isnan
from functools import partial
from io import StringIO
from os import path as p, environ, O_NONBLOCK
from decimal import Decimal
from json import loads
from html.entities import name2codepoint
from html.parser import HTMLParser

try:
    from urllib.error import URLError
except ImportError:
    from six.moves.urllib_error import URLError

import pygogo as gogo

from builtins import *
from six.moves.urllib.parse import quote, urlparse
from six.moves.urllib.request import urlopen

from riko.dates import TODAY, cast_date
from riko.currencies import CURRENCY_CODES
from riko.locations import LOCATIONS
from mezmorize import Cache
from meza.fntools import Objectify, SleepyDict, remove_keys, listize
from meza.process import merge
from meza._compat import decode
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

URL_SAFE = "%/:=&?~#+!$,;'@()*[]"

NAMESPACES = {
    'owl': 'http://www.w3.org/2002/07/owl#',
    'xhtml': 'http://www.w3.org/1999/xhtml'}

ESCAPE = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;'}

SKIP_SWITCH = {
    'contains': lambda text, value: text.lower() in value.lower(),
    'intersection': lambda text, value: set(text).intersection(value),
    're.search': lambda text, value: re.search(text, value),
}

url_quote = lambda url: quote(url, safe=URL_SAFE)


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


def get_response_encoding(response, def_encoding='utf-8'):
    info = response.info()

    try:
        encoding = info.getencoding()
    except AttributeError:
        encoding = info.get_charset()

    encoding = None if encoding == '7bit' else encoding

    if not encoding and hasattr(info, 'get_content_charset'):
        encoding = info.get_content_charset()

    if not encoding and hasattr(response, 'getheader'):
        content_type = response.getheader('Content-Type', '')

        if 'charset' in content_type:
            ctype = content_type.split('=')[1]
            encoding = ctype.strip().strip('"').strip("'")

    return encoding or def_encoding


def parse_rss(url, delay=0):
    context = SleepyDict(delay=delay)
    response = None

    try:
        response = urlopen(decode(url), context=context)
    except TypeError:
        try:
            response = urlopen(decode(url))
        except (ValueError, URLError):
            parsed = rssparser.parse(url)
    except (ValueError, URLError):
        parsed = rssparser.parse(url)

    if response:
        content = response.read() if speedparser else response

        try:
            parsed = rssparser.parse(content)
        finally:
            response.close()

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
        raise TypeError('Invalid file type %s' % ext)

    return content


def cast_url(url_str):
    url = 'http://%s' % url_str if '://' not in url_str else url_str
    quoted = url_quote(url)
    parsed = urlparse(quoted)
    response = parsed._asdict()
    response['url'] = parsed.geturl()
    return response


def lookup_street_address(address):
    location = {
        'lat': 0, 'lon': 0, 'country': 'United States', 'admin1': 'state',
        'admin2': 'county', 'admin3': 'city', 'city': 'city',
        'street': 'street', 'postal': '61605'}

    return location


def lookup_ip_address(address):
    location = {
        'country': 'United States', 'admin1': 'state', 'admin2': 'county',
        'admin3': 'city', 'city': 'city'}

    return location


def lookup_coordinates(lat, lon):
    location = {
        'lat': lat, 'lon': lon, 'country': 'United States', 'admin1': 'state',
        'admin2': 'county', 'admin3': 'city', 'city': 'city',
        'street': 'street', 'postal': '61605'}

    return location


def cast_location(address, loc_type='street_address'):
    GEOLOCATERS = {
        'coordinates': lambda x: lookup_coordinates(*x),
        'street_address': lambda x: lookup_street_address(x),
        'ip_address': lambda x: lookup_ip_address(x),
        'currency': lambda x: CURRENCY_CODES.get(x, {}),
    }

    result = GEOLOCATERS[loc_type](address)

    if result.get('location'):
        extra = LOCATIONS.get(result['location'], {})
        result.update(extra)

    return result


CAST_SWITCH = {
    'float': {'default': float('nan'), 'func': float},
    'decimal': {'default': Decimal('NaN'), 'func': Decimal},
    'int': {'default': 0, 'func': lambda i: int(float(i))},
    'text': {'default': '', 'func': str},
    'date': {'default': {'date': TODAY}, 'func': cast_date},
    'url': {'default': {}, 'func': cast_url},
    'location': {'default': {}, 'func': cast_location},
    'bool': {'default': False, 'func': lambda i: bool(loads(i))},
    'pass': {'default': None, 'func': lambda i: i},
    'none': {'default': None, 'func': lambda _: None},
}


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
            skip = SKIP_SWITCH[op](text, value) if text else value

            if not _skip.get('include'):
                skip = not skip

            if skip:
                break
    else:
        skip = False

    return skip


def get_field(item, field=None, **kwargs):
    return item.get(field, **kwargs) if field else item


def get_abspath(url):
    url = 'http://%s' % url if url and '://' not in url else url

    if url and url.startswith('file:///'):
        # already have an abspath
        pass
    elif url and url.startswith('file://'):
        parent = p.dirname(p.dirname(__file__))
        rel_path = url[7:]
        abspath = p.abspath(p.join(parent, rel_path))
        url = 'file://%s' % abspath

    return decode(url)


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
