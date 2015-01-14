# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.lib.utils
    ~~~~~~~~~~~~~~~~~
    Utility functions

"""

from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import string
import re

from collections import namedtuple
from datetime import datetime
from functools import partial
from itertools import (
    groupby, chain, izip, tee, takewhile, ifilter, imap, starmap)
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

star_func = lambda item, func: func(item)
imap_func = lambda funcs, items: starmap(star_func, izip(items, funcs))
combine_dicts = lambda *d: dict(chain.from_iterable(imap(dict.items, d)))
cache = Cache(**cache_config)
timeout = 60 * 60 * 1
sub_rule = {'match': re.compile('\$(\d+)'), 'replace': r'\\\1', 'count': 0}


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


def group_by(data, attr, default=None):
    groups = {}

    # like operator.itemgetter but fills in missing keys with a default value
    keyfunc = lambda item: lambda obj: obj.get(item, default)
    data.sort(key=keyfunc(attr))

    for key, values in groupby(data, keyfunc(attr)):
        groups[str(key)] = list(v for v in values)

    return groups


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
    elif content and not set(i.keys()).difference(['content']):
        # element is leaf node and doesn't have attributes
        i = content

    return i


def make_finite(_INPUT):
    yield _INPUT.next()

    for i in takewhile(lambda i: not 'forever' in i, _INPUT):
        yield i


def get_value(field, item=None, **kwargs):
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
        if not hasattr(field, 'delete'):
            raise TypeError('field must be of type DotDict')
        else:
            value = field.get(None, **kwargs)
    except (TypeError, AttributeError):
        # field is already set to a value so use it or the default
        value = field or kwargs.get('default')
    except (ValueError):
        # error converting subkey value with OPS['func'] so use the default
        value = kwargs.get('default')

    return value


def broadcast(_INPUT, *funcs):
    splits = izip(*tee(_INPUT, len(funcs)))
    return imap(partial(imap_func, funcs), splits)


def dispatch(splits, *funcs):
    return imap(partial(imap_func, funcs), splits)


def gather(splits, func):
    gather_func = lambda split: func(*list(split))
    return imap(gather_func, splits)


def parse_conf(conf, item=None, parse_func=None, **kwargs):
    parse = kwargs.pop('parse', True)
    keys = conf.keys()
    iterable = map(lambda k: conf[k], keys)
    values = map(partial(parse_func, item=item), iterable)

    if parse:
        Conf = namedtuple('Conf', keys)
        result = Conf(*values)
    else:
        result = dict(zip(keys, values))

    return result


def parse_params(params):
    true_params = ifilter(all, params)
    return dict(imap(lambda x: (x.key, x.value), true_params))


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


def get_word(item):
    try:
        word = ''.join(item.itervalues())
    except AttributeError:
        word = item
    except TypeError:
        word = None

    return word or ''


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


def substitute(word, rule):
    return rule['match'].sub(rule['replace'], word, rule['count'])


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
    replace = fix_pattern(rule['replace'], sub_rule)
    matchc = re.compile(rule['match'], flags) if recompile else rule['match']

    rule = {
        'match': matchc,
        'replace': replace,
        'field': field,
        'count': count,
        'flags': flags
    }

    return rule


def convert_rules(rules, recompile=False):
    # Convert replace pattern to Python/Linux format
    rule_func = partial(get_new_rule, recompile=recompile)
    return imap(rule_func, rules)


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


def multiplex(sources):
    """Combine multiple generators into one"""
    return chain.from_iterable(sources)
