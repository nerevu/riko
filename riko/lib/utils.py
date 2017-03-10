# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.lib.utils
~~~~~~~~~~~~~~
Provides utility classes and functions
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import re
import itertools as it
import time
import pygogo as gogo

try:
    import __builtin__ as _builtins
except ImportError:
    import builtins as _builtins

from datetime import timedelta, datetime as dt
from functools import partial
from operator import itemgetter, add, sub
from os import path as p, environ
from calendar import timegm
from decimal import Decimal
from json import loads

from builtins import *
from six.moves.urllib.parse import quote, urlparse
from six.moves.urllib.request import urlopen

try:
    from urllib.error import URLError
except ImportError:
    from six.moves.urllib_error import URLError

from mezmorize import Cache
from dateutil import parser
from ijson import items
from meza._compat import decode

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

global CACHE

rssparser = speedparser or feedparser

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
    'yesterday': TODAY - timedelta(days=1)}

NAMESPACES = {
    'owl': 'http://www.w3.org/2002/07/owl#',
    'xhtml': 'http://www.w3.org/1999/xhtml'}

url_quote = lambda url: quote(url, safe=URL_SAFE)


class Objectify(object):
    """Creates an object with dynamically set attributes. Useful
    for accessing the kwargs of a function as attributes.
    """
    def __init__(self, initialdata, func=None, **defaults):
        """ Objectify constructor

        Args:
            initialdata (dict): The attributes to set
            defaults (dict): The default attributes

        Examples:
            >>> initialdata = {'one': 1, 'two': 2}
            >>> defaults = {'two': 5, 'three': 3}
            >>> kw = Objectify(initialdata, **defaults)
            >>> sorted(kw) == ['one', 'three', 'two']
            True
            >>> dict(kw) == {'one': 1, 'two': 2, 'three': 3}
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
        defaults.update(initialdata)
        self.data = defaults
        self.func = func
        self.get = self.data.get
        self.keys = self.data.keys
        self.values = self.data.values
        self.items = self.data.items
        self.__setitem__ = self.data.__setitem__
        self.__delitem__ = self.data.__delitem__
        self.__setattr__ = self.data.__setitem__
        self.__delattr__ = self.data.__delitem__

    def __repr__(self):
        return repr(self.data)

    def __getitem__(self, name):
        return self.data.__getitem__(name)

    def __getattr__(self, name):
        attr = self.get(name)
        return self.func(attr) if self.func else attr

    def __iter__(self):
        return iter(self.data)


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
        funcs = (partial(getattr, x) for x in [self.data, _builtins, it])
        zipped = zip(funcs, it.repeat(AttributeError))
        method = multi_try(name, zipped, default=None)
        return Chainable(self.data, method)

    def __call__(self, *args, **kwargs):
        try:
            return Chainable(self.method(self.data, *args, **kwargs))
        except TypeError:
            return Chainable(self.method(args[0], self.data, **kwargs))


def combine_dicts(*dicts):
    iterable = (d.items() for d in dicts)
    return dict(it.chain.from_iterable(iterable))


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


def get_cache_config(cache_type='simple'):
    CONFIGS = {
        'sasl': {
            'CACHE_TYPE': 'saslmemcached',
            'CACHE_MEMCACHED_SERVERS': [environ.get('MEMCACHIER_SERVERS')],
            'CACHE_MEMCACHED_USERNAME': environ.get('MEMCACHIER_USERNAME'),
            'CACHE_MEMCACHED_PASSWORD': environ.get('MEMCACHIER_PASSWORD')},
        'simple': {
            'DEBUG': True,
            'CACHE_TYPE': 'simple',
            'CACHE_THRESHOLD': 25},
        'memcached': {
            'DEBUG': True,
            'CACHE_TYPE': 'memcached',
            'CACHE_MEMCACHED_SERVERS': [environ.get('MEMCACHE_SERVERS')]}}

    return CONFIGS[cache_type]


def set_cache(cache_config):
    global CACHE
    CACHE = Cache(**cache_config)

CACHE = Cache(**get_cache_config())


# http://api.stackexchange.com/2.2/tags?
# page=1&pagesize=100&order=desc&sort=popular&site=stackoverflow
# http://api.stackexchange.com/2.2/tags?
# page=1&pagesize=100&order=desc&sort=popular&site=graphicdesign
def memoize(*args, **kwargs):
    return CACHE.memoize(*args, **kwargs)


def remove_keys(content, *args):
    """ Remove keys from a dict and return new dict

    Args:
        content (dict): The dict to remove keys from
        args (List[str]): The keys to remove

    Returns:
        dict: New dict with specified keys removed

    Examples:
        >>> content = {'keep': 1, 'remove': 2}
        >>> remove_keys(content, 'remove') == {'keep': 1}
        True
        >>> remove_keys(Objectify(content), 'remove') == {'keep': 1}
        True
    """
    return {k: v for k, v in content.items() if k not in args}


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


def get_response_encoding(response, def_encoding='utf-8'):
    info = response.info()

    try:
        encoding = info.getencoding()
    except AttributeError:
        encoding = info.get_charset()

    encoding = None if encoding == '7bit' else encoding

    if not encoding:
        try:
            encoding = info.get_content_charset()
        except AttributeError:
            pass

    if not encoding:
        try:
            content_type = response.getheader('Content-Type', '')
        except AttributeError:
            pass
        else:
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
        tags = path.split('/')[1:] or [path]

        try:
            elements = tree.getElementsByTagName(tags[pos]) if tags else [tree]
        except AttributeError:
            element_name = str(tree).split(' ')[1]

            if not namespace and {'{', '}'}.issubset(element_name):
                start, end = element_name.find('{') + 1, element_name.find('}')
                ns = element_name[start:end]
                ns_iter = (name for name in NAMESPACES if name in ns)
                namespace = next(ns_iter, namespace)

            prefix = ('/%s:' % namespace) if namespace else '/'
            match = '.%s%s' % (prefix, prefix.join(tags[1:]))
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
            date = parser.parse(date_str)
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
    parsed = urlparse(quoted)
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
        'text': {'default': '', 'func': str},
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

    return decode(url)


def listize(item):
    if hasattr(item, 'keys'):
        listlike = False
    else:
        attrs = {'append', '__next__', 'next', '__reversed__'}
        listlike = attrs.intersection(dir(item))

    return item if listlike else [item]


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


# def extend_entry(entry):
#     if entry.get('k:tags'):
#         if len(tags.split(',')) < 2:
#             tags = tags.replace(' ', ',')

#         tags = tags.replace('/', ',').replace('#', '').replace(' ', '_')
#         tags = filter(None, sorted(set(parse_tags(tags.split(',')))))
#     else:
#         tags = []

#     content = entry.get('k:content').replace('<br />', '')
#     content = content.replace('\n', '').strip()

#     entry['k:tags'] = tags
#     entry['k:content'] = content
#     entry['k:summary'] = '%s%s' % (content[:128].replace('...', ''), '...')
#     return entry


############
# Generators
############
def gen_entries(parsed):
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
