# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.lib.utils
    ~~~~~~~~~~~~~~~~~
    Utility functions

"""

from __future__ import absolute_import, division, print_function

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
from pipe2py import Context
from mezmorize import Cache

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
        cache_config = {'DEBUG': True, 'CACHE_TYPE': 'simple'}
    else:
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

# leave option to substitute with multiprocessing
_map_func = imap

combine_dicts = lambda *d: dict(chain.from_iterable(imap(dict.iteritems, d)))
cache = Cache(**cache_config)
timeout = 60 * 60 * 1


class Objectify:
    def __init__(self, **entries):
        self.__dict__.update(entries)

    def __iter__(self):
        return self.__dict__.itervalues()

    def iteritems(self):
        return self.__dict__.iteritems()


def _apply_func(funcs, items, map_func=starmap):
    return map_func(lambda item, func: func(item), izip(items, funcs))


def memoize(*args, **kwargs):
    return cache.memoize(*args, **kwargs)


def extract_dependencies(pipe_def=None, pipe_generator=None):
    """Extract modules used by a pipe"""
    if pipe_def:
        pydeps = gen_dependencies(pipe_def)
    elif pipe_generator:
        pydeps = pipe_generator(Context(describe_dependencies=True))
    else:
        raise Exception('Must supply at least one kwarg!')

    return sorted(set(pydeps))


def extract_input(pipe_def=None, pipe_generator=None):
    """Extract inputs required by a pipe"""
    if pipe_def:
        pyinput = gen_input(pipe_def)
    elif pipe_generator:
        pyinput = pipe_generator(Context(describe_input=True))
    else:
        raise Exception('Must supply at least one kwarg!')

    return sorted(list(pyinput))


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
    ordered = {key: grouped[key] for key in order}
    return ordered


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


def finitize(_INPUT):
    yield _INPUT.next()

    for i in takewhile(lambda i: not 'forever' in i, _INPUT):
        yield i


def get_value(field, item=None, force=False, **kwargs):
    item = item or {}

    OPS = {
        'number': {'default': 0.0, 'func': float},
        'integer': {'default': 0, 'func': int},
        'text': {'default': ''},
        'unicode': {'default': '', 'func': unicode},
        'bool': {'default': False, 'func': lambda i: bool(int(i))},
    }

    try:
        kwargs.update(OPS.get(field.get('type', 'text'), {}))
    except AttributeError:
        kwargs.update(OPS['text'])

    try:
        value = item.get(field['subkey'], **kwargs)
    except KeyError:
        if field and not (hasattr(field, 'delete') or force):
            raise TypeError('field must be of type DotDict')
        elif force:
            value = field
        elif field:
            value = field.get(None, **kwargs)
        else:
            value = kwargs.get('default')
    except (TypeError, AttributeError):
        # field is already set to a value so use it or the default
        value = field or kwargs.get('default')
    except (ValueError):
        # error converting subkey value with OPS['func'] so use the default
        value = kwargs.get('default')

    return value


def broadcast(_INPUT, *funcs, **kwargs):
    """copies an iterable and delivers the items to multiple functions

           /--> foo2bar(_INPUT) --> \
          /                          \
    _INPUT ---> foo2baz(_INPUT) ---> _OUTPUT
          \                          /
           \--> foo2qux(_INPUT) --> /

    One way to construct such a flow in code would be::

        _INPUT = repeat('foo', 3)
        foo2bar = lambda word: word.replace('foo', 'bar')
        foo2baz = lambda word: word.replace('foo', 'baz')
        foo2qux = lambda word: word.replace('foo', 'quz')
        _OUTPUT = broadcast(_INPUT, foo2bar, foo2baz, foo2qux)
        _OUTPUT == repeat(('bar', 'baz', 'qux'), 3)
    """
    map_func = kwargs.get('map_func', _map_func)
    apply_func = kwargs.get('apply_func', _apply_func)
    splits = izip(*tee(_INPUT, len(funcs)))
    return map_func(partial(apply_func, funcs), splits)


def dispatch(splits, *funcs, **kwargs):
    """takes multiple iterables (returned by dispatch or broadcast) and delivers
    the items to multiple functions

           /-----> _INPUT1 --> double(_INPUT1) --> \
          /                                         \
    splits ------> _INPUT2 --> triple(_INPUT2) ---> _OUTPUT
          \                                         /
           \--> _INPUT3 --> quadruple(_INPUT3) --> /

    One way to construct such a flow in code would be::

        splits = repeat(('bar', 'baz', 'qux'), 3)
        double = lambda word: word * 2
        triple = lambda word: word * 3
        quadruple = lambda word: word * 4
        _OUTPUT = dispatch(splits, double, triple, quadruple)
        _OUTPUT == repeat(('barbar', 'bazbazbaz', 'quxquxquxqux'), 3)
    """
    map_func = kwargs.get('map_func', _map_func)
    apply_func = kwargs.get('apply_func', _apply_func)
    return map_func(partial(apply_func, funcs), splits)


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
        submodule/system

       Assumes conf has name, default, prompt and debug
    """
    name = conf['name']['value']
    prompt = conf['prompt']['value']
    default = conf['default']['value'] or conf['debug']['value']

    if context.submodule or context.inputs:
        value = context.inputs.get(name, default)
    elif not context.test:
        # we skip user interaction during tests
        value = raw_input(
            "%s (default=%s) " % (
                prompt.encode('utf-8'), default.encode('utf-8'))
        ) or default
    else:
        value = default

    return value


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

    return url


def get_word(item):
    try:
        word = ''.join(item.itervalues())
    except AttributeError:
        word = item
    except TypeError:
        word = None

    return str(word.encode('utf-8')) if isinstance(word, unicode) else word


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
    try:
        return quote(url, safe=URL_SAFE)
    except KeyError:
        return quote(url.encode('utf-8'), safe=URL_SAFE)


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


def fix_pattern(word, rule):
    if '$' in word:
        pattern = rule['match'].sub(rule['replace'], word, rule['count'])
    else:
        pattern = word

    return pattern


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
        entry['dc:creator'] = entry.get('author')
        entry['author.uri'] = entry.get('author_detail', {}).get(
            'href')
        entry['author.name'] = entry.get('author_detail', {}).get(
            'name')
        entry['pubDate'] = entry.get('updated_parsed')
        entry['y:published'] = entry.get('updated_parsed')
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


def gen_dependencies(pipe_def):
    for module in pipe_def['modules']:
        yield 'pipe%s' % module['type']

        try:
            yield 'pipe%s' % module['conf']['embed']['value']['type']
        except (KeyError, TypeError):
            pass


def gen_input(pipe_def):
    fields = ['position', 'name', 'prompt']

    for module in pipe_def['modules']:
        # Note: there seems to be no need to recursively collate inputs
        # from subpipelines
        try:
            module_confs = [module['conf'][x]['value'] for x in fields]
        except (KeyError, TypeError):
            pass
        else:
            values = ['type', 'value']
            module_confs.extend((module['conf']['default'][x] for x in values))
            yield tuple(module_confs)


def gen_names(module_ids, pipe, ntype='module'):
    for module_id in module_ids:
        module_type = pipe['modules'][module_id]['type']

        if module_type.startswith('pipe:'):
            name = pythonise(module_type)
        elif ntype == 'module':
            name = 'pipe%s' % module_type
        elif ntype == 'pipe':
            name = 'pipe_%s' % module_type
        else:
            raise Exception(
                "Invalid type: %s. (Expected 'module' or 'pipe')" % ntype)

        yield name


def gen_modules(pipe_def):
    for module in listize(pipe_def['modules']):
        yield (pythonise(module['id']), module)


def gen_embedded_modules(pipe_def):
    for module in listize(pipe_def['modules']):
        if module['type'] == 'loop':
            embed = module['conf']['embed']['value']
            yield (pythonise(embed['id']), embed)


def gen_wires(pipe_def):
    for wire in listize(pipe_def['wires']):
        yield (pythonise(wire['id']), wire)


def gen_graph1(pipe_def):
    for module in listize(pipe_def['modules']):
        yield (pythonise(module['id']), [])

        # make the loop dependent on its embedded module
        if module['type'] == 'loop':
            embed = module['conf']['embed']['value']
            yield (pythonise(embed['id']), [pythonise(module['id'])])


def gen_graph2(pipe_def):
    for wire in listize(pipe_def['wires']):
        src_id = pythonise(wire['src']['moduleid'])
        tgt_id = pythonise(wire['tgt']['moduleid'])
        yield (src_id, tgt_id)


def gen_graph3(graph):
    # Remove any orphan nodes
    values = graph.values()

    for node, value in graph.iteritems():
        targetted = (node in v for v in values)

        if value or any(targetted):
            yield (node, value)
