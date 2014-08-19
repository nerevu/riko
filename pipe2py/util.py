"""Utility functions"""
# vim: sw=4:ts=4:expandtab

import string

from datetime import datetime
from urllib2 import quote
from os import path as p
from operator import itemgetter
from itertools import repeat
from pipe2py import Context

try:
    from json import loads
except (ImportError, AttributeError):
    from simplejson import loads

DATE_FORMAT = "%m/%d/%Y"
ALTERNATIVE_DATE_FORMATS = (
    "%m-%d-%Y",
    "%m/%d/%y",
    "%m/%d/%Y",
    "%m-%d-%y",
    "%Y-%m-%dt%H:%M:%Sz",
    # todo more: whatever Yahoo can accept
)

DATETIME_FORMAT = DATE_FORMAT + " %H:%M:%S"
URL_SAFE = "%/:=&?~#+!$,;'@()*[]"


def extract_modules(pipe_file_name=None, pipe_def=None, pipe_generator=None):
    """Extract modules used by a pipe"""
    if pipe_file_name:
        with open(pipe_file_name) as f:
            pjson = f.read()

    if pipe_file_name or pipe_def:
        pipe_def = pipe_def or loads(pjson)
        num = len(pipe_def['modules'])
        modules = map(dict.get, pipe_def['modules'], repeat('type', num))

        for m in pipe_def['modules']:
            try:
                if m['conf'].get('embed'):
                    modules.append(m['conf']['embed']['value']['type'])
            except AttributeError:
                pass
    else:
        modules = pipe_generator(Context(describe_dependencies=True))

    return sorted(set(modules))


def pythonise(id, encoding='ascii'):
    """Return a Python-friendly id"""
    replace = {'-': '_', ':': '_', '/': '_'}

    for key, value in replace.items():
        id = id.replace(key, value)

    id = '_%s' % id if id[0] in string.digits else id
    return id.encode(encoding)


def _make_content(i, tag, new):
    content = i.get(tag)

    if content and new:
        content = content if hasattr(content, 'append') else [content]
        content.append(new)
    elif new:
        content = new

    return content


def etree_to_dict(element):
    """Convert an eTree xml into dict imitating how Yahoo Pipes does it.

    todo: further investigate white space and multivalue handling
    """
    i = dict(element.items())
    content = element.text.strip() if element.text else None
    i.update({'content': content}) if content else None

    if len(element.getchildren()):
        for child in element.iterchildren():
            tag = child.tag.split('}', 1)[-1]
            new = etree_to_dict(child)
            content = _make_content(i, tag, new)
            i.update({tag: content}) if content else None

            tag = 'content'
            new = child.tail.strip() if child.tail else None
            content = _make_content(i, tag, new)
            i.update({tag: content}) if content else None
    elif content and not set(i.keys()).difference(['content']):
        # element is leaf node and doesn't have attributes
        i = content

    return i


def multikeysort(items, columns):
    """Sorts a list of items by the columns

       (columns precedeed with a '-' will sort descending)
    """
    comparers = [
        (
            (itemgetter(col[1:].strip()), -1) if col.startswith('-') else (
                itemgetter(col.strip()), 1
            )
        ) for col in columns
    ]

    def comparer(left, right):
        for fn, mult in comparers:
            try:
                result = cmp(fn(left), fn(right))
            except KeyError:
                # todo: perhaps care more if only one side has the missing key
                result = 0
            except TypeError:  # todo: handle bool better?
                # todo: perhaps care more if only one side has the missing key
                result = 0
            if result:
                return mult * result
        else:
            return 0
    return sorted(items, cmp=comparer)


def get_value(field, item=None, default=None, encode=False, func=False, **kwargs):
    try:
        if item and field.get('subkey'):
            value = item.get(field['subkey'], default, encode, func, **kwargs)
        else:
            value = field.get(None, default, encode, func, **kwargs)
    except AttributeError:
        value = None

    return value


def get_date(date_string):
    for date_format in ALTERNATIVE_DATE_FORMATS:
        try:
            return datetime.strptime(date_string, date_format)
        except ValueError:
            pass


def get_input(context, conf):
    """Gets a user parameter, either from the console or from an outer
        submodule/system

       Assumes conf has name, default, prompt and debug
    """
    name = conf['name']['value']
    default = conf['default']['value']
    prompt = conf['prompt']['value']
    # debug = conf['debug']['value']

    value = None

    if context.submodule:
        value = context.inputs.get(name, default)
    elif context.test:
        # we skip user interaction during tests
        # note: docs say debug is used, but doesn't seem to be
        value = default
    elif context.console:
        value = raw_input(
            prompt.encode('utf-8') + (
                " (default=%s) " % default.encode('utf-8')
            )
        )
        if value == "":
            value = default
    else:
        value = context.inputs.get(name, default)

    return value


def get_abspath(url):
    url = 'http://%s' % url if url and '://' not in url else url

    if url.startswith('file:///'):
        # already have an abspath
        pass
    elif url.startswith('file://'):
        parent = p.dirname(__file__)
        rel_path = url[7:]
        abspath = p.abspath(p.join(parent, rel_path))
        url = 'file://%s' % abspath

    return url


def rreplace(s, find, replace, count=None):
    li = s.rsplit(find, count)
    return replace.join(li)


def url_quote(url):
    """Ensure url is valid"""
    try:
        return quote(url, safe=URL_SAFE)
    except KeyError:
        return quote(url.encode('utf-8'), safe=URL_SAFE)


def listize(item):
    return item if hasattr(item, 'append') else [item]


############
# Generators
############
def gen_entries(parsed):
    for entry in parsed['entries']:
        entry['pubDate'] = entry.get('updated_parsed')
        entry['y:published'] = entry.get('updated_parsed')
        entry['dc:creator'] = entry.get('author')
        entry['author.uri'] = entry.get('author_detail', {}).get(
            'href')
        entry['author.name'] = entry.get('author_detail', {}).get(
            'name')
        entry['y:title'] = entry.get('title')
        entry['y:id'] = entry.get('id')
        # TODO: more?
        yield entry


def gen_items(item, yield_if_none=False):
    if item and hasattr(item, 'append'):
        for nested_item in item:
            yield nested_item
    elif item:
        yield item
    elif yield_if_none:
        yield

