# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.lib.utils
    ~~~~~~~~~~~~~~~~~
    Utility functions

"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

import string
import re
import itertools as it
import time

# from pprint import pprint
from datetime import datetime
from functools import partial
from operator import itemgetter
from urllib2 import quote
from os import path as p, environ
from collections import defaultdict
from pipe2py import Context
from pipe2py.lib.log import Logger
from mezmorize import Cache

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
ALTERNATIVE_DATE_FORMATS = (
    "%m-%d-%Y",
    "%m/%d/%y",
    "%m/%d/%Y",
    "%m-%d-%y",
    "%Y-%m-%dt%H:%M:%Sz",
    # todo more: whatever Yahoo can accept
)

TIMEOUT = 60 * 60 * 1
HALF_DAY = 60 * 60 * 12

combine_dicts = lambda *d: dict(it.chain.from_iterable(it.imap(dict.iteritems, d)))
encode = lambda w: str(w.encode('utf-8')) if isinstance(w, unicode) else w


class Objectify:
    def __init__(self, kwargs, **defaults):
        """ Objectify constructor

        Args:
            kwargs (dict): The attributes to set
            defaults (dict): The default attributes

        Examples:
            >>> kwargs = {'one': 1, 'two': 2}
            >>> defaults = {'two': 5, 'three': 3}
            >>> kw = Objectify(kwargs, **defaults)
            >>> kw
            Objectify({u'three': 3, u'two': 2, u'one': 1})
            >>> str(kw)
            'Objectify(one=1, three=3, two=2)'
            >>> sorted(kw.keys()) == ['one', 'three', 'two']
            True
            >>> kw.one
            1
            >>> kw.two
            2
            >>> kw.three
            3
            >>> kw.four
        """
        defaults.update(kwargs)
        self.__dict__.update(defaults)

    def __str__(self):
        items = sorted(self.__dict__.items())
        args = ', '.join('%s=%s' % item for item in items)
        return '%s(%s)' % (self.__class__.__name__, args)

    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__, self.__dict__)

    def __iter__(self):
        return self.__dict__.itervalues()

    def __getattr__(self, name):
        return None

    def to_dict(self):
        return self.__dict__

    def items(self):
        return self.__dict__.items()

    def iteritems(self):
        return self.__dict__.iteritems()

    def keys(self):
        return self.__dict__.keys()


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
        funcs = (partial(getattr, x) for x in [self.data, builtins, itertools])
        zipped = izip(funcs, repeat(AttributeError))
        method = multi_try(name, zipped, default=None)
        return Chainable(self.data, method)

    def __call__(self, *args, **kwargs):
        try:
            return Chainable(self.method(self.data, *args, **kwargs))
        except TypeError:
            return Chainable(self.method(args[0], self.data, **kwargs))


# http://api.stackexchange.com/2.2/tags?
# page=1&pagesize=100&order=desc&sort=popular&site=stackoverflow
# http://api.stackexchange.com/2.2/tags?
# page=1&pagesize=100&order=desc&sort=popular&site=graphicdesign
def memoize(*args, **kwargs):
    return Cache(**cache_config).memoize(*args, **kwargs)


def remove_keys (content, *args):
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
    groups = it.groupby(sorted_iterable, keyfunc(attr))
    grouped = {str(k): list(v) for k, v in groups}

    # return groups in original order
    return {key: grouped[key] for key in order}


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

    todo: further investigate white space and multivalue handling
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


def get_value(item, conf=None, force=False, **opts):
    item = item or {}

    switch = {
        'number': {'default': 0.0, 'func': float},
        'integer': {'default': 0, 'func': int},
        'text': {'default': '', 'func': encode},
        'unicode': {'default': '', 'func': unicode},
        'bool': {'default': False, 'func': lambda i: bool(int(i))},
    }

    try:
        defaults = switch.get(conf.get('type', 'text'), {})
    except AttributeError:
        defaults = switch['text']

    kwargs = defaultdict(str, **defaults)
    kwargs.update(opts)
    default = kwargs['default']

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
        value = conf or default
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
    parsed = {k: get_value(item, kw.conf[k]) for k in kw.conf}
    result = combine_dicts(kw.defaults, parsed)
    return Objectify(result) if kw.objectify else result


def parse_params(item, conf=None, **kwargs):
    parsed = {k: get_value(item, conf[k]) for k in conf}
    return {parsed['key']: parsed['value']}


def get_skip(item, skip_if=None, **kwargs):
    item = item or {}
    return skip_if and skip_if(item)


def get_field(item, field=None, **kwargs):
    return item.get(field, **kwargs) if field else item


def get_date(date_string):
    for date_format in ALTERNATIVE_DATE_FORMATS:
        try:
            return datetime.strptime(date_string, date_format)
        except ValueError:
            pass


def get_input(context, conf):
    """Gets a user parameter, either from the console or from an outer
    system

       Assumes conf has name, default, prompt and debug
    """
    name = conf['name']['value']
    prompt = conf['prompt']['value']
    default = conf['default']['value'] or conf['debug']['value']

    if context.inputs:
        value = context.inputs.get(name, default)
    elif not context.test:
        raw = raw_input("%s (default=%s) " % (prompt, default))
        value = raw or default
    else:
        value = default

    return value


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


def get_word(item):
    try:
        raw = ''.join(item.itervalues())
    except AttributeError:
        raw = item
    except TypeError:
        raw = None

    return raw or ''


def get_num(item):
    try:
        joined = ''.join(item.itervalues())
    except AttributeError:
        joined = item

    try:
        num = float(joined)
    except (ValueError, TypeError):
        num = 0.0

    return num


def rreplace(s, find, replace, count=None):
    li = s.rsplit(find, count)
    return replace.join(li)


def url_quote(url):
    """Ensure url is valid"""
    return quote(url, safe=URL_SAFE)


def listize(item):
    listlike = set(['append', 'next', '__reversed__']).intersection(dir(item))
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
            item = it.ifilter(itemgetter(1), match.groupdict().iteritems()).next()

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

            # words = list(words)
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
        result = rule['match'].sub(rule['replace'], word, rule['count'])
    else:
        result = word

    return result


# @memoize(TIMEOUT)
def fix_pattern(word, rule):
    if '$' in word:
        pattern = rule['match'].sub(rule['replace'], word, rule['count'])
    else:
        pattern = word

    return pattern


# @memoize(TIMEOUT)
def get_new_rule(rule, recompile=False):
    # flag 'i' --> 2
    flags = re.IGNORECASE if rule.get('ignorecase') else 0

    # flag 'm' --> 8
    flags |= re.MULTILINE if rule.get('multilinematch') else 0

    # flag 's' --> 16
    flags |= re.DOTALL if rule.get('singlelinematch') else 0

    # flag 'g' --> 0
    count = 0 if rule.get('globalmatch') else 1
    field = rule.get('field')

    if recompile:
        fix = {'match': re.compile('\$(\d+)'), 'replace': r'\\\1', 'count': 0}
        replace = fix_pattern(rule['replace'], fix)
        matchc = re.compile(rule['match'], flags)
    else:
        replace = rule['replace']
        matchc = rule['match']

    nrule = {
        'match': matchc,
        'replace': replace,
        'field': field,
        'count': count,
        'flags': flags,
        'series': rule.get('seriesmatch', True),
        'offset': int(rule.get('offset') or 0),
    }

    return nrule


def convert_rules(rules, recompile=False):
    # Convert replace pattern to Python/Linux format
    rule_func = partial(get_new_rule, recompile=recompile)
    return it.imap(rule_func, rules)


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


def gen_items(item, yield_if_none=False):
    if item and hasattr(item, 'append'):
        for nested_item in item:
            yield nested_item
    elif item:
        yield item
    elif yield_if_none:
        yield
