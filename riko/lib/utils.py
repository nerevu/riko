# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    riko.lib.utils
    ~~~~~~~~~~~~~~~~~
    Utility functions

"""

from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import __builtin__
import string
import re
import itertools as it
import time

# from pprint import pprint
from datetime import timedelta, datetime as dt
from functools import partial
from operator import itemgetter, add, sub
from urllib2 import quote
from os import path as p, environ
from calendar import timegm
from decimal import Decimal
from urllib import urlencode
from urlparse import urlparse
from json import loads

from builtins import *
from mezmorize import Cache
from dateutil.parser import parse

from riko.lib.log import Logger

logger = Logger(__name__).logger

if environ.get('DATABASE_URL'):  # HEROKU
    cache_config = {
        'CACHE_TYPE': 'saslmemcached',
        'CACHE_MEMCACHED_SERVERS': [environ.get('MEMCACHIER_SERVERS')],
        'CACHE_MEMCACHED_USERNAME': environ.get('MEMCACHIER_USERNAME'),
        'CACHE_MEMCACHED_PASSWORD': environ.get('MEMCACHIER_PASSWORD')}
else:
    try:
        import pylibmc
    except ImportError:
        logger.debug('simplecache')
        cache_config = {
            'DEBUG': True,
            'CACHE_TYPE': 'simple',
            'CACHE_THRESHOLD': 25}
    else:
        logger.debug('memcached')
        cache_config = {
            'DEBUG': True,
            'CACHE_TYPE': 'memcached',
            'CACHE_MEMCACHED_SERVERS': [environ.get('MEMCACHE_SERVERS')]}

DATE_FORMAT = '%m/%d/%Y'
DATETIME_FORMAT = '{0} %H:%M:%S'.format(DATE_FORMAT)
URL_SAFE = "%/:=&?~#+!$,;'@()*[]"
TIMEOUT = 60 * 60 * 1
HALF_DAY = 60 * 60 * 12
TODAY = dt.utcnow()

DATES = {
    'today': TODAY,
    'now': TODAY,
    'tomorrow': TODAY + timedelta(days=1),
    'yesterday': TODAY - timedelta(days=1),
}

url_quote = lambda url: quote(url, safe=URL_SAFE)


class Objectify(dict):
    def __init__(self, kwargs, func=None, **defaults):
        """ Objectify constructor

        Args:
            kwargs (dict): The attributes to set
            defaults (dict): The default attributes

        Examples:
            >>> kwargs = {'one': 1, 'two': 2}
            >>> defaults = {'two': 5, 'three': 3}
            >>> kw = Objectify(kwargs, **defaults)
            >>> sorted(kw.keys()) == ['one', 'three', 'two']
            True
            >>> kw == {u'three': 3, u'two': 2, u'one': 1}
            True
            >>> kw.one
            1
            >>> kw.two
            2
            >>> kw.three
            3
            >>> kw.four
            >>> kw.get('one')
            1
        """
        defaults.update(kwargs)
        super(Objectify, self).__init__(defaults)
        self.func = func
        self.__setattr__ = dict.__setitem__
        self.__delattr__ = dict.__delitem__

    def __getattribute__(self, name):
        good = {
            'get', 'pop', 'keys', 'items', 'iteritems', 'func', 'viewitems',
            'viewkeys'}

        if name in good:
            return object.__getattribute__(self, name)
        else:
            attr = self.get(name)
            return self.func(attr) if self.func else attr



class SleepyDict(dict):
    """A dict like object that sleeps for a specified amount of time before
    returning a key or during truth value testing
    """
    def __init__(self, *args, **kwargs):
        self.delay = kwargs.pop('delay', 0)
        super(SleepyDict, self).__init__(*args, **kwargs)

    def __len__(self):
        time.sleep(self.delay)
        return super(SleepyDict, self).__len__()

    def get(self, key, default=None):
        time.sleep(self.delay)
        return super(SleepyDict, self).get(key, default)


class Chainable(object):
    def __init__(self, data, method=None):
        self.data = data
        self.method = method
        self.list = list(data)

    def __getattr__(self, name):
        funcs = (partial(getattr, x) for x in [self.data, __builtin__, it])
        zipped = it.izip(funcs, it.repeat(AttributeError))
        method = multi_try(name, zipped, default=None)
        return Chainable(self.data, method)

    def __call__(self, *args, **kwargs):
        try:
            return Chainable(self.method(self.data, *args, **kwargs))
        except TypeError:
            return Chainable(self.method(args[0], self.data, **kwargs))


def combine_dicts(*dicts):
    return dict(it.chain.from_iterable(it.imap(dict.iteritems, dicts)))


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


# http://api.stackexchange.com/2.2/tags?
# page=1&pagesize=100&order=desc&sort=popular&site=stackoverflow
# http://api.stackexchange.com/2.2/tags?
# page=1&pagesize=100&order=desc&sort=popular&site=graphicdesign
def memoize(*args, **kwargs):
    return Cache(**cache_config).memoize(*args, **kwargs)


def remove_keys(content, *args):
    """Remove keys from a dict and return new dict"""
    return {k: v for k, v in content.items() if k not in args}


def pythonise(id, encoding='ascii'):
    """Return a Python-friendly id"""
    replace = {'-': '_', ':': '_', '/': '_'}
    func = lambda id, pair: id.replace(pair[0], pair[1])
    id = reduce(func, replace.iteritems(), id)
    id = '_%s' % id if id[0] in string.digits else id
    return id.encode(encoding)


def group_by(iterable, attr, default=None):
    # like operator.itemgetter but fills in missing keys with a default value
    keyfunc = lambda item: lambda obj: obj.get(item, default)
    data = list(iterable)
    order = unique_everseen(data, keyfunc(attr))
    sorted_iterable = sorted(data, key=keyfunc(attr))
    grouped = it.groupby(sorted_iterable, keyfunc(attr))
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


def etree_to_dict(element):
    """Convert an lxml element into a dict imitating how Yahoo Pipes does it.
    """
    i = dict(element.items())
    i.update(_make_content(i, element.text, strip=True))

    for child in element.iterchildren():
        tag = child.tag
        value = etree_to_dict(child)
        i.update(_make_content(i, value, tag))

    if element.text and not set(i).difference(['content']):
        # element is leaf node and doesn't have attributes
        i = i['content']

    return i


def cast_date(date_str):
    try:
        words = date_str.split(' ')
    except AttributeError:
        date = date_str
    else:
        date = None
        math_words = {
            'seconds', 'minutes', 'hours', 'days', 'weeks', 'months', 'years'}
        text_words = {'last', 'next', 'week', 'month', 'year'}
        mathish = set(words).intersection(math_words)
        textish = set(words).intersection(text_words)

    if date:
        pass
    elif date_str[0] in {'+', '-'} and len(mathish) == 1:
        op = sub if date_str.startswith('-') else add
        date = get_date(mathish, words[0][1:], op)
    elif len(textish) == 2:
        op = add if date_str.startswith('last') else add
        date = get_date('%ss' % words[1], 1, op)
    elif date_str in DATES:
        date = DATES.get(date_str)
    else:
        try:
            date = parse(date_str)
        except AttributeError:
            date = time.gmtime(date_str)

    keys = (
        'year', 'month', 'day', 'hour', 'minute', 'second', 'day_of_week',
        'day_of_year', 'daylight_savings')

    try:
        tt = date.timetuple()
    except AttributeError:
        tt, date = date, dt(*date[:6])

    # Make Sunday the first day of the week
    day_of_w = 0 if tt[6] == 6 else tt[6] + 1
    isdst = None if tt[8] == -1 else bool(tt[8])
    result = {'utime': timegm(tt), 'timezone': 'UTC', 'date': date}
    result.update(zip(keys, tt))
    result.update({'day_of_week': day_of_w, 'daylight_savings': isdst})
    return result


def cast_url(url_str):
    url = 'http://%s' % url_str if '://' not in url_str else url_str
    quoted = url_quote(url)
    parsed = urlparse(url)
    response = parsed._asdict()
    response['url'] = parsed.geturl()
    return response


def cast_location(location_str):
    # TODO: Fix this for real!
    location = {
        'lat': 0, 'lon': 0, 'quality': 0, 'country': 'US', 'admin1': 'state',
        'admin2': 'county', 'admin3': 'city', 'city': 'city',
        'street': 'street', 'postal': '61605'}

    return location


def cast(content, _type='text'):
    switch = {
        'float': {'default': 0.0, 'func': float},
        'decimal': {'default': Decimal(0), 'func': Decimal},
        'int': {'default': 0, 'func': int},
        'text': {'default': u'', 'func': unicode},
        'date': {'default': {'date': TODAY}, 'func': cast_date},
        'url': {'default': {}, 'func': cast_url},
        'location': {'default': {}, 'func': cast_location},
        'bool': {'default': False, 'func': lambda i: bool(loads(i))},
        'pass': {'default': None, 'func': lambda i: i},
        'none': {'default': None, 'func': lambda _: None},
    }

    if content is None:
        value = switch[_type]['default']
    else:
        value = switch[_type]['func'](content)

    return value


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
    return [func(item) for item, func in it.izip(split, funcs)]


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


def parse_conf(item, **kwargs):
    kw = Objectify(kwargs, defaults={}, conf={})
    # TODO: fix so .items() returns a DotDict instance
    # parsed = {k: get_value(item, v) for k, v in kw.conf.items()}
    sentinel = {'subkey', 'value', 'terminal'}
    not_dict = not hasattr(kw.conf, 'keys')

    if not_dict or (len(kw.conf) == 1 and sentinel.intersection(kw.conf)):
        objectified = get_value(item, **kwargs)
    else:
        parsed = {k: get_value(item, kw.conf[k]) for k in kw.conf}
        result = combine_dicts(kw.defaults, parsed)
        objectified = Objectify(result) if kw.objectify else result

    return objectified


def get_skip(item, skip_if=None, **kwargs):
    item = item or {}
    return skip_if and skip_if(item)


def get_field(item, field=None, **kwargs):
    return item.get(field, **kwargs) if field else item


def get_date(unit, count, op):
    dates = {
        'seconds': op(TODAY, timedelta(seconds=count)),
        'minutes': op(TODAY, timedelta(minutes=count)),
        'hours': op(TODAY, timedelta(hours=count)),
        'days': op(TODAY, timedelta(days=count)),
        'weeks': op(TODAY, timedelta(weeks=count)),
        # TODO: fix for when new month is not in 1..12
        'months': TODAY.replace(month=op(TODAY.month, count)),
        'years': TODAY.replace(year=op(TODAY.year, count)),
    }

    return dates[unit]


def get_abspath(url):
    url = 'http://%s' % url if url and '://' not in url else url

    if url and url.startswith('file:///'):
        # already have an abspath
        pass
    elif url and url.startswith('file://'):
        parent = p.dirname(p.dirname(p.dirname(__file__)))
        rel_path = url[7:]
        abspath = p.abspath(p.join(parent, rel_path))
        url = 'file://%s' % abspath

    return url


def listize(item):
    if hasattr(item, 'keys'):
        listlike = False
    else:
        listlike = {'append', 'next', '__reversed__'}.intersection(dir(item))

    return item if listlike else [item]


def _gen_words(match, splits):
    groups = list(it.dropwhile(lambda x: not x, match.groups()))

    for s in splits:
        try:
            num = int(s)
        except ValueError:
            word = s
        else:
            word = it.islice(groups, num, num + 1).next()

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
    rules_in_series = it.ifilter(itemgetter('series'), rules)
    rules_in_parallel = (r for r in rules if not r['series'])

    try:
        has_parallel = [rules_in_parallel.next()]
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
            items = match.groupdict().iteritems()
            item = it.ifilter(itemgetter(1), items).next()

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
        yield entry


def gen_items(content, key):
    if hasattr(content, 'append'):
        for nested in content:
            for i in gen_items(nested, key):
                yield i
    elif content:
        yield {key: content}
