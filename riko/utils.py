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
import fcntl

from math import isnan
from functools import partial
from operator import itemgetter
from os import O_NONBLOCK, path as p
from io import BytesIO, StringIO, TextIOBase
from urllib.error import HTTPError, URLError

from six.moves.urllib.request import urlopen

import requests
import pygogo as gogo

try:
    import __builtin__ as _builtins
except ImportError:
    import builtins as _builtins

from builtins import *  # noqa pylint: disable=unused-import
from mezmorize import memoize
from meza.io import reencode
from meza.compat import decode
from meza.fntools import SleepyDict
from riko import ENCODING
from riko.cast import cast

logger = gogo.Gogo(__name__, verbose=False, monolog=True).logger

DEF_NS = 'https://github.com/nerevu/riko'


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


# https://trac.edgewall.org/ticket/2066#comment:1
# http://stackoverflow.com/a/22675049/408556
def make_blocking(f):
    fd = f.fileno()
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)

    if flags & O_NONBLOCK:
        blocking = flags & ~O_NONBLOCK
        fcntl.fcntl(fd, fcntl.F_SETFL, blocking)


if 'nose' in sys.modules:
    logger.debug('Running in nose environment...')
    make_blocking(sys.stderr)


class Chainable(object):
    def __init__(self, data, method=None):
        self.data = data
        self.method = method
        self.list = list(data)

    def __getattr__(self, name):
        funcs = (partial(getattr, x) for x in [self.data, _builtins, it])
        zipped = zip(funcs, it.repeat(AttributeError))
        method = multi_try(name, zipped, default=None)
        return Chainable(self.data, method)

    def __call__(self, *args, **kwargs):
        try:
            return Chainable(self.method(self.data, *args, **kwargs))
        except TypeError:
            return Chainable(self.method(args[0], self.data, **kwargs))


def invert_dict(d):
    return {v: k for k, v in d.items()}


def multi_try(source, zipped, default=None):
    value = None

    for func, error in zipped:
        try:
            value = func(source)
        except error:
            pass
        else:
            return value
    else:
        return default


def get_response_content_type(response):
    try:
        content_type = response.getheader('Content-Type', '')
    except AttributeError:
        content_type = response.headers.get('Content-Type', '')

    return content_type.lower()


def get_response_encoding(response, def_encoding=ENCODING):
    info = response.info()

    try:
        encoding = info.getencoding()
    except AttributeError:
        encoding = info.get_charset()

    encoding = None if encoding == '7bit' else encoding

    if not encoding and hasattr(info, 'get_content_charset'):
        encoding = info.get_content_charset()

    if not encoding:
        content_type = get_response_content_type(response)

        if 'charset' in content_type:
            ctype = content_type.split('=')[1]
            encoding = ctype.strip().strip('"').strip("'")

    extracted = encoding or def_encoding
    assert extracted
    return extracted


# https://docs.python.org/3.3/reference/expressions.html#examples
def auto_close(stream, f):
    try:
        for record in stream:
            yield record
    finally:
        f.close()


class fetch(TextIOBase):
    # http://stackoverflow.com/a/22836333/408556
    def __init__(self, url=None, params=None, decode=False, **kwargs):
        delay = kwargs.get('delay')
        params = params or {}

        self.r = None
        self.ext = None
        self.context = SleepyDict(delay=delay) if delay else None
        self.decode = decode
        self.def_encoding = kwargs.get('encoding', ENCODING)
        self.cache_type = kwargs.get('cache_type')
        self.timeout = kwargs.get('timeout')

        if self.cache_type:
            memoizer = memoize(**kwargs)
            opener = memoizer(self.open)
            self.cache_type = memoizer.cache_type
            self.client_name = memoizer.client_name
        else:
            opener = self.open
            self.cache_type = self.client_name = None

        response = opener(get_abspath(url), **params)
        wrapper = StringIO if self.decode else BytesIO
        f = wrapper(response) if self.cache_type else response
        self.close = f.close
        self.read = f.read
        self.readline = f.readline

        try:
            self.seek = f.seek
        except AttributeError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.r.close() if self.r else None
        self.close()

    def open(self, url, **params):
        if url.startswith('http') and params:
            r = requests.get(url, params=params, stream=True)
            r.raw.decode_content = self.decode
            response = r.text if self.cache_type else r.raw
        else:
            try:
                r = urlopen(url, context=self.context, timeout=self.timeout)
            except TypeError:
                r = urlopen(url, timeout=self.timeout)
            except HTTPError as e:
                msg = '{} returned {}: {}'
                raise URLError(msg.format(url, e.code, e.reason))
            except URLError as e:
                raise URLError('{}: {}'.format(url, e.reason))

            text = r.read() if self.cache_type else None

            if self.decode:
                encoding = get_response_encoding(r, self.def_encoding)

                if text:
                    response = decode(text, encoding)
                else:
                    response = reencode(r.fp, encoding, decode=True)
            else:
                response = text or r

        content_type = get_response_content_type(r)

        if 'xml' in content_type:
            self.ext = 'xml'
        elif 'json' in content_type:
            self.ext = 'json'
        else:
            self.ext = content_type.split('/')[1].split(';')[0]

        self.r = r
        return response


def def_itemgetter(attr, default=0, _type=None):
    # like operator.itemgetter but fills in missing keys with a default value
    def keyfunc(item):
        value = item.get(attr, default)
        casted = cast(value, _type) if _type else value

        try:
            is_nan = isnan(casted)
        except TypeError:
            is_nan = False

        return default if is_nan else casted

    return keyfunc


# TODO: move this to meza.process.group
def group_by(iterable, attr, default=None):
    keyfunc = def_itemgetter(attr, default)
    data = list(iterable)
    order = unique_everseen(data, keyfunc)
    sorted_iterable = sorted(data, key=keyfunc)
    grouped = it.groupby(sorted_iterable, keyfunc)
    groups = {str(k): list(v) for k, v in grouped}

    # return groups in original order
    return ((key, groups[key]) for key in order)


def unique_everseen(iterable, key=None):
    # List unique elements, preserving order. Remember all elements ever seen
    # unique_everseen('ABBCcAD', str.lower) --> a b c d
    seen = set()

    for element in iterable:
        k = str(key(element))

        if k not in seen:
            seen.add(k)
            yield k


def betwix(iterable, start=None, stop=None, inc=False):
    """ Extract selected elements from an iterable. But unlike `islice`,
    extract based on the element's value instead of its position.

    Args:
        iterable (iter): The initial sequence
        start (str): The fragment to begin with (inclusive)
        stop (str): The fragment to finish at (exclusive)
        inc (bool): Make stop operate inclusively (useful if reading a file and
            the start and stop fragments are on the same line)

    Returns:
        Iter: New dict with specified keys removed

    Examples:
        >>> from io import StringIO
        >>>
        >>> list(betwix('ABCDEFG', stop='C')) == ['A', 'B']
        True
        >>> list(betwix('ABCDEFG', 'C', 'E')) == ['C', 'D']
        True
        >>> list(betwix('ABCDEFG', 'C')) == ['C', 'D', 'E', 'F', 'G']
        True
        >>> f = StringIO('alpha\\n<beta>\\ngamma\\n')
        >>> list(betwix(f, '<', '>', True)) == ['<beta>\\n']
        True
        >>> list(betwix('ABCDEFG', 'C', 'E', True)) == ['C', 'D', 'E']
        True
    """
    def inc_takewhile(predicate, _iter):
        for x in _iter:
            yield x

            if not predicate(x):
                break

    get_pred = lambda sentinel: lambda x: sentinel not in x
    pred = get_pred(stop)
    first = it.dropwhile(get_pred(start), iterable) if start else iterable

    if stop and inc:
        last = inc_takewhile(pred, first)
    elif stop:
        last = it.takewhile(pred, first)
    else:
        last = first

    return last


def dispatch(split, *funcs):
    """takes a tuple of items and delivers each item to a different function

           /--> item1 --> double(item1) -----> \
          /                                     \
    split ----> item2 --> triple(item2) -----> _OUTPUT
          \                                     /
           \--> item3 --> quadruple(item3) --> /

    One way to construct such a flow in code would be::

        split = ('bar', 'baz', 'qux')
        double = lambda word: word * 2
        triple = lambda word: word * 3
        quadruple = lambda word: word * 4
        _OUTPUT = dispatch(split, double, triple, quadruple)
        _OUTPUT == ('barbar', 'bazbazbaz', 'quxquxquxqux')
    """
    return [func(item) for item, func in zip(split, funcs)]


def broadcast(item, *funcs):
    """delivers the same item to different functions

           /--> item --> double(item) -----> \
          /                                   \
    item -----> item --> triple(item) -----> _OUTPUT
          \                                   /
           \--> item --> quadruple(item) --> /

    One way to construct such a flow in code would be::

        double = lambda word: word * 2
        triple = lambda word: word * 3
        quadruple = lambda word: word * 4
        _OUTPUT = broadcast('bar', double, triple, quadruple)
        _OUTPUT == ('barbar', 'bazbazbaz', 'quxquxquxqux')
    """
    return [func(item) for func in funcs]


def _gen_words(match, splits):
    groups = list(it.dropwhile(lambda x: not x, match.groups()))

    for s in splits:
        try:
            num = int(s)
        except ValueError:
            word = s
        else:
            word = next(it.islice(groups, num, num + 1))

        yield word


def multi_substitute(word, rules):
    """ Apply multiple regex rules to 'word'
    http://code.activestate.com/recipes/
    576710-multi-regex-single-pass-replace-of-multiple-regexe/
    """
    flags = rules[0]['flags']

    # Create a combined regex from the rules
    tuples = ((p, r['match']) for p, r in enumerate(rules))
    regexes = ('(?P<match_%i>%s)' % (p, r) for p, r in tuples)
    pattern = '|'.join(regexes)
    regex = re.compile(pattern, flags)
    resplit = re.compile('\$(\d+)')

    # For each match, look-up corresponding replace value in dictionary
    rules_in_series = filter(itemgetter('series'), rules)
    rules_in_parallel = (r for r in rules if not r['series'])

    try:
        has_parallel = [next(rules_in_parallel)]
    except StopIteration:
        has_parallel = []

    # print('================')
    # pprint(rules)
    # print('word:', word)
    # print('pattern', pattern)
    # print('flags', flags)

    for _ in it.chain(rules_in_series, has_parallel):
        # print('~~~~~~~~~~~~~~~~')
        # print('new round')
        # print('word:', word)
        # found = list(regex.finditer(word))
        # matchitems = [match.groupdict().items() for match in found]
        # pprint(matchitems)
        prev_name = None
        prev_is_series = None
        i = 0

        for match in regex.finditer(word):
            items = match.groupdict().items()
            item = next(filter(itemgetter(1), items))

            # print('----------------')
            # print('groupdict:', match.groupdict().items())
            # print('item:', item)

            if not item:
                continue

            name = item[0]
            rule = rules[int(name[6:])]
            series = rule.get('series')
            kwargs = {'count': rule['count'], 'series': series}
            is_previous = name is prev_name
            singlematch = kwargs['count'] is 1
            is_series = prev_is_series or kwargs['series']
            isnt_previous = bool(prev_name) and not is_previous

            if (is_previous and singlematch) or (isnt_previous and is_series):
                continue

            prev_name = name
            prev_is_series = series

            if resplit.findall(rule['replace']):
                splits = resplit.split(rule['replace'])
                words = _gen_words(match, splits)
            else:
                splits = rule['replace']
                start = match.start() + i
                end = match.end() + i
                words = [word[:start], splits, word[end:]]
                i += rule['offset']

            word = ''.join(words)

            # print('name:', name)
            # print('prereplace:', rule['replace'])
            # print('splits:', splits)
            # print('resplits:', resplit.findall(rule['replace']))
            # print('groups:', filter(None, match.groups()))
            # print('i:', i)
            # print('words:', words)
            # print('range:', match.start(), '-', match.end())
            # print('replace:', word)

    # print('substitution:', word)
    return word


def substitute(word, rule):
    if word:
        result = rule['match'].subn(rule['replace'], word, rule['count'])
        replaced, replacements = result

        if rule.get('default') is not None and not replacements:
            replaced = rule.get('default')
    else:
        replaced = word

    return replaced


def get_new_rule(rule, recompile=False):
    flags = 0 if rule.get('casematch') else re.IGNORECASE

    if not rule.get('singlelinematch'):
        flags |= re.MULTILINE
        flags |= re.DOTALL

    count = 1 if rule.get('singlematch') else 0

    if recompile and '$' in rule['replace']:
        replace = re.sub('\$(\d+)', r'\\\1', rule['replace'], 0)
    else:
        replace = rule['replace']

    match = re.compile(rule['match'], flags) if recompile else rule['match']

    nrule = {
        'match': match,
        'replace': replace,
        'default': rule.get('default'),
        'field': rule.get('field'),
        'count': count,
        'flags': flags,
        'series': rule.get('seriesmatch', True),
        'offset': int(rule.get('offset') or 0),
    }

    return nrule


def multiplex(sources):
    """Combine multiple generators into one"""
    return it.chain.from_iterable(sources)


def gen_entries(parsed):
    if parsed.get('bozo_exception'):
        raise Exception(parsed['bozo_exception'])

    for entry in parsed['entries']:
        # prevent feedparser deprecation warnings
        if 'published_parsed' in entry:
            updated = entry['published_parsed']
        else:
            updated = entry.get('updated_parsed')

        entry['pubDate'] = updated
        entry['y:published'] = updated
        entry['dc:creator'] = entry.get('author')
        entry['author.uri'] = entry.get('author_detail', {}).get(
            'href')
        entry['author.name'] = entry.get('author_detail', {}).get(
            'name')
        entry['y:title'] = entry.get('title')
        entry['y:id'] = entry.get('id')
        yield entry


def gen_items(content, key=None):
    if hasattr(content, 'append'):
        for nested in content:
            for i in gen_items(nested, key):
                yield i
    elif content:
        yield {key: content} if key else content
