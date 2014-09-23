"""Utility functions"""
# vim: sw=4:ts=4:expandtab

import string

from datetime import datetime
from urllib2 import quote
from os import path as p
from pipe2py import Context

try:
    from json import loads
except (ImportError, AttributeError):
    from simplejson import loads

ALTERNATIVE_DATE_FORMATS = (
    "%m-%d-%Y",
    "%m/%d/%y",
    "%m/%d/%Y",
    "%m-%d-%y",
    "%Y-%m-%dt%H:%M:%Sz",
    # todo more: whatever Yahoo can accept
)

DATE_FORMAT = '%m/%d/%Y'
DATETIME_FORMAT = '{0} %H:%M:%S'.format(DATE_FORMAT)
URL_SAFE = "%/:=&?~#+!$,;'@()*[]"


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


def get_value(field, item=None, default=None, **kwargs):
    try:
        if item and field.get('subkey'):
            value = item.get(field['subkey'], default, **kwargs)
        else:
            value = field.get(None, default, **kwargs)
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


def gen_rules(rule_defs, fields, **kwargs):
    for rule in rule_defs:
        if not hasattr(rule, 'delete'):
            raise TypeError('rule must be of type DotDict')

        yield tuple(rule.get(field, **kwargs) for field in fields)


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

    for node, value in graph.items():
        targetted = [node in v for v in values]

        if value or any(targetted):
            yield (node, value)


###########################################################
# Generator Tricks for Systems Programmers by David Beazley
###########################################################
def _gen_cat(sources):
    """Feed a generated sequence into a queue
    Concatenate multiple generators into a single sequence
    """
    for s in sources:
        for item in s:
            yield item


def _send_to_queue(source, queue):
    """Feed a generated sequence into a queue
    """
    for item in source:
        queue.put(item)
    queue.put(StopIteration)


def _gen_from_queue(queue):
    """Generate items received on a queue
    """
    while True:
        item = queue.get()

        if item is StopIteration:
            break

        yield item


def _gen_multiplex(sources, target, generator, queue, Thread):
    """Generate threads to run the generator and send items to a shared queue
    """
    for src in sources:
        thr = Thread(target=target, args=(src, queue))
        thr.start()
        yield generator(queue)


def multiplex(sources):
    """Consume several generators in parallel
    """
    from Queue import Queue
    from threading import Thread

    queue = Queue()
    consumers = _gen_multiplex(
        sources, _send_to_queue, _gen_from_queue, queue, Thread)

    return _gen_cat(consumers)
