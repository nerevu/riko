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

# from pprint import pprint
from datetime import datetime
from functools import partial
from itertools import (
    groupby, chain, izip, tee, takewhile, ifilter, imap, starmap, islice,
    dropwhile)
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

combine_dicts = lambda *d: dict(chain.from_iterable(imap(dict.iteritems, d)))
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
            >>> kw.one
            1
            >>> kw.two
            2
            >>> kw.three
            3
        """
        defaults.update(kwargs)
        self.__dict__.update(defaults)

    def __iter__(self):
        return self.__dict__.itervalues()

    def iteritems(self):
        return self.__dict__.iteritems()


def _apply_func(funcs, items, map_func=starmap):
    return map_func(lambda item, func: func(item), izip(items, funcs))

# http://api.stackexchange.com/2.2/tags?
# page=1&pagesize=100&order=desc&sort=popular&site=stackoverflow
# http://api.stackexchange.com/2.2/tags?
# page=1&pagesize=100&order=desc&sort=popular&site=graphicdesign


def memoize(*args, **kwargs):
    return Cache(**cache_config).memoize(*args, **kwargs)





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
    groups = groupby(sorted_iterable, keyfunc(attr))
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


def _make_content(i, tag, new):
    content = i.get(tag)

    if content and new:
        content = listize(content)
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
    elif content and not set(i).difference(['content']):
        # element is leaf node and doesn't have attributes
        i = content

    return i


def get_value(field, item=None, force=False, **opts):
    item = item or {}

    switch = {
        'number': {'default': 0.0, 'func': float},
        'integer': {'default': 0, 'func': int},
        'text': {'default': '', 'func': encode},
        'unicode': {'default': '', 'func': unicode},
        'bool': {'default': False, 'func': lambda i: bool(int(i))},
    }

    try:
        defaults = switch.get(field.get('type', 'text'), {})
    except AttributeError:
        defaults = switch['text']

    kwargs = defaultdict(str, **defaults)
    kwargs.update(opts)
    default = kwargs['default']

    try:
        value = item.get(field['subkey'], **kwargs)
    except KeyError:
        if field and not (hasattr(field, 'delete') or force):
            raise TypeError('field must be of type DotDict')
        elif force:
            value = field
        elif field:
            value = field.get(**kwargs)
        else:
            value = default
    except (TypeError, AttributeError):
        # field is already set to a value so use it or the default
        value = field or default
    except (ValueError):
        # error converting subkey value with OPS['func'] so use the default
        value = default

    return value


def dispatch(split, *funcs, **kwargs):
    """takes a tuple of items (returned by dispatch or broadcast) and delivers
    each item to different function

           /----> item1 --> double(item1) --> \
          /                                    \
    split ----> item2 --> triple(item2) ---> _OUTPUT
          \                                    /
           \-> item3 --> quadruple(item3) --> /

    One way to construct such a flow in code would be::

        split = ('bar', 'baz', 'qux')
        double = lambda word: word * 2
        triple = lambda word: word * 3
        quadruple = lambda word: word * 4
        _OUTPUT = dispatch(split, double, triple, quadruple)
        _OUTPUT == ('barbar', 'bazbazbaz', 'quxquxquxqux')
    """
    map_func = kwargs.get('map_func', starmap)
    return map_func(lambda item, func: func(item), izip(split, funcs))


def parse_conf(conf, item=None, parse_func=None, **kwargs):
    convert = kwargs.pop('convert', True)
    values = map(partial(parse_func, item=item), (conf[c] for c in conf))
    result = dict(zip(conf, values))
    return Objectify(**result) if convert else result


def parse_params(params):
    true_params = filter(all, params)
    return dict((x.key, x.value) for x in true_params)


def get_pass(item=None, test=None):
    item = item or {}
    return test and test(item)


def get_with(item, **kwargs):
    loop_with = kwargs.pop('with', None)
    return item.get(loop_with, **kwargs) if loop_with else item


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


def passthrough(item):
    return item


def passnone(item):
    return None


def rreplace(s, find, replace, count=None):
    li = s.rsplit(find, count)
    return replace.join(li)


def url_quote(url):
    """Ensure url is valid"""
    return quote(url, safe=URL_SAFE)


def listize(item):
    listlike = set(['append', 'next']).intersection(dir(item))
    return item if listlike else [item]


def _gen_words(match, splits):
    groups = list(dropwhile(lambda x: not x, match.groups()))

    for s in splits:
        try:
            num = int(s)
        except ValueError:
            word = s
        else:
            word = islice(groups, num, num + 1).next()

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
    rules_in_series = ifilter(itemgetter('series'), rules)
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

    for _ in chain(rules_in_series, has_parallel):
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
            item = ifilter(itemgetter(1), match.groupdict().iteritems()).next()

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
    return imap(rule_func, rules)


def multiplex(sources):
    """Combine multiple generators into one"""
    return chain.from_iterable(sources)


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
