"""Utility functions"""
# vim: sw=4:ts=4:expandtab

import string

from urllib2 import quote
from os import path as p
from operator import itemgetter
from itertools import repeat

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


def extract_modules(pipe_file_name=None, pipe_def=None):
    """Extract modules used by a pipe"""
    if pipe_file_name:
        with open(pipe_file_name) as f:
            pjson = f.read()

    pipe_def = pipe_def or loads(pjson)
    num = len(pipe_def['modules'])
    modules = map(dict.get, pipe_def['modules'], repeat('type', num))

    for m in pipe_def['modules']:
        try:
            if m['conf'].get('embed'):
                modules.append(m['conf']['embed']['value']['type'])
        except AttributeError:
            pass

    return sorted(set(modules))


def pythonise(id):
    """Return a Python-friendly id"""
    if id:
        id = id.replace("-", "_").replace(":", "_")

        if id[0] in string.digits:
            id = "_" + id

        return id.encode('ascii')


def xml_to_dict(element):
    """Convert xml into dict"""
    i = dict(element.items())
    if element.getchildren():
        if element.text and element.text.strip():
            i['content'] = element.text
        for child in element.getchildren():
            if str(child)[:4] == '<!--':
                continue
            tag = child.tag.split('}', 1)[-1]
            i[tag] = xml_to_dict(child)
    else:
        if not i.keys():
            if element.text and element.text.strip():
                i = element.text
        else:
            if element.text and element.text.strip():
                i['content'] = element.text

    return i


def etree_to_pipes(element):
    """Convert ETree xml into dict imitating how Yahoo Pipes does it.

    todo: further investigate white space and multivalue handling
    """
    # start as a dict of attributes
    i = dict(element.items())
    if len(element):  # if element has child elements
        if element.text and element.text.strip():  # if element has text
            i['content'] = element.text

        for child in element:
            if str(child)[:4] == '<!--':
                continue
            tag = child.tag.split('}', 1)[-1]

            # process child recursively and append it to parent dict
            subtree = etree_to_pipes(child)
            content = i.get(tag)
            if content is None:
                content = subtree
            elif isinstance(content, list):
                content = content + [subtree]
            else:
                content = [content, subtree]
            i[tag] = content

            if child.tail and child.tail.strip():  # if text after child
                # append to text content of parent
                text = child.tail
                content = i.get('content')
                if content is None:
                    content = text
                elif isinstance(content, list):
                    content = content + [text]
                else:
                    content = [content, text]
                i['content'] = content
    else:  # element is leaf node
        if not i.keys():  # if element doesn't have attributes
            if element.text and element.text.strip():  # if element has text
                i = element.text
        else:  # element has attributes
            if element.text and element.text.strip():  # if element has text
                i['content'] = element.text

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
