"""Compile/Translate Yahoo Pipe into Python

    Takes a JSON representation of a Yahoo pipe and either:
     a) translates it into a Python script containing a function
        (using generators to build the pipeline) or
     b) compiles it as a pipeline of generators which can be executed
        in-process

    Usage:
     a) python pipe2py/compile.py tests/pipelines/testpipe1.json
        python pipe2py/pypipelines/testpipe1.py

     b) from pipe2py import compile, Context

        pipe_def = json.loads(pjson)
        pipe = parse_pipe_def(pipe_def, pipe_name)
        pipeline = build_pipeline(Context(), pipe)
        print list(pipeline)

    Instead of passing a filename, a pipe id can be passed (-p) to fetch the
    JSON from Yahoo, e.g.

        python compile.py -p 2de0e4517ed76082dcddf66f7b218057

    Author: Greg Gaughan
    Idea: Tony Hirst (http://ouseful.wordpress.com/2010/02/25/starting-to-think-about-a-yahoo-pipes-code-generator)
    Python generator pipelines inspired by:
        David Beazely (http://www.dabeaz.com/generators-uk)
    auto-rss module by Mark Pilgrim

   License: see LICENSE file
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import fileinput
import sys
import requests

try:
    from json import loads, dumps
except (ImportError, AttributeError):
    from simplejson import loads, dumps

from codecs import open
from itertools import chain, izip
from collections import defaultdict
from importlib import import_module
from pprint import PrettyPrinter
from jinja2 import Environment, PackageLoader
from optparse import OptionParser
from os import path as p
from pipe2py import Context, util
from pipe2py.modules.pipeforever import pipe_forever
from pipe2py.lib.pprint2 import Id, repr_args, str_args
from pipe2py.lib.topsort import topological_sort

PARENT = p.dirname(__file__)


class MyPrettyPrinter(PrettyPrinter):
    def format(self, object, context, maxlevels, level):
        if isinstance(object, unicode):
            return (object.encode('utf8'), True, False)
        else:
            return PrettyPrinter.format(
                self, object, context, maxlevels, level)


def write_file(data, path, pretty=False):
    if data and path:
        with open(path, 'w', encoding='utf-8') as f:
            if hasattr(data, 'keys') and pretty:
                data = dumps(data, sort_keys=True, indent=4, ensure_ascii=False)
            elif hasattr(data, 'keys'):
                data = dumps(data, ensure_ascii=False)
            elif pretty:
                data = unicode(MyPrettyPrinter().pformat(data), 'utf-8')

            return f.write(data)


def _load_json(json):
    try:
        loaded = loads(json.encode('utf-8'))
    except UnicodeDecodeError:
        loaded = loads(json)

    return loaded


def _get_zipped(context, pipe, **kwargs):
    module_ids = kwargs['module_ids']
    module_names = kwargs['module_names']
    pipe_names = kwargs['pipe_names']
    return izip(module_ids, module_names, pipe_names)


def _gen_string_modules(context, pipe, zipped):
    for module_id, module_name, pipe_name in zipped:
        pyargs = _get_pyargs(context, pipe, module_id)
        pykwargs = dict(_gen_pykwargs(context, pipe, module_id))

        if context and context.verbose:
            con_args = filter(lambda x: x != Id('context'), args)
            nconf_kwargs = filter(lambda x: x[0] != 'conf', pykwargs.items())
            conf_kwargs = filter(lambda x: x[0] == 'conf', pykwargs.items())
            all_args = chain(con_args, nconf_kwargs, conf_kwargs)

            print (
                '%s = %s(%s)' % (
                    module_id, pipe_name, str_args(all_args)
                )
            ).encode('utf-8')

        yield {
            'args': repr_args(chain(pyargs, pykwargs.items())),
            'id': module_id,
            'sub_pipe': module_name.startswith('pipe_'),
            'name': module_name,
            'pipe_name': pipe_name,
        }


def _gen_steps(context, pipe, **kwargs):
    module_id = kwargs['module_id']
    module_name = kwargs['module_name']
    pipe_name = kwargs['pipe_name']
    steps = kwargs['steps']

    if module_name.startswith('pipe_'):
        # Import any required sub-pipelines and user inputs
        # Note: assumes they have already been compiled to accessible .py
        # files
        import_name = 'pipe2py.pypipelines.%s' % module_name
    else:
        import_name = 'pipe2py.modules.%s' % module_name

    module = import_module(import_name)
    pipe_generator = getattr(module, pipe_name)

    # if this module is an embedded module:
    if module_id in pipe['embed']:
        # We need to wrap submodules (used by loops) so we can pass the
        # input at runtime (as we can to sub-pipelines)
        # Note: no embed (so no subloops) or wire pykwargs are passed
        pipe_generator.__name__ = str('pipe_%s' % module_id)
        yield (module_id, pipe_generator)
    else:  # else this module is not embedded:
        pyargs = _get_pyargs(context, pipe, module_id, steps)
        pykwargs = dict(_gen_pykwargs(context, pipe, module_id, steps))
        yield (module_id, pipe_generator(*pyargs, **pykwargs))


def _get_steps(context, pipe, zipped):
    steps = {'forever': pipe_forever()}

    for module_id, module_name, pipe_name in zipped:
        kwargs = {
            'module_id': module_id,
            'module_name': module_name,
            'pipe_name': pipe_name,
            'steps': steps,
        }

        steps.update(dict(_gen_steps(context, pipe, **kwargs)))

    return steps


def _get_pyargs(context, pipe, module_id, steps=None):
    describe = context.describe_input or context.describe_dependencies

    if not (describe and steps):
        # find the default input of this module
        input_module = _get_input_module(pipe, module_id, steps)

        return [context, input_module] if steps else [
            Id('context'), Id(input_module)]


def _gen_pykwargs(context, pipe, module_id, steps=None):
    module = pipe['modules'][module_id]
    yield ('conf', module['conf'])
    describe = context.describe_input or context.describe_dependencies

    if not (describe and steps):
        wires = pipe['wires']
        module_type = module['type']

        # find the default input of this module
        for key, pipe_wire in wires.items():
            moduleid = util.pythonise(pipe_wire['src']['moduleid'])

            # todo? this equates the outputs
            is_default_out_only = (
                util.pythonise(pipe_wire['tgt']['moduleid']) == module_id
                and pipe_wire['tgt']['id'] != '_INPUT'
                and pipe_wire['src']['id'].startswith('_OUTPUT')
            )

            # if the wire is to this module and it's *NOT* the default input
            # but it *is* the default output
            if is_default_out_only:
                # set the extra inputs of this module as pykwargs of this module
                pipe_id = util.pythonise(pipe_wire['tgt']['id'])
                yield (pipe_id, steps[moduleid] if steps else Id(moduleid))

        # set the embedded module in the pykwargs if this is loop module
        if module_type == 'loop':
            value = module['conf']['embed']['value']
            pipe_id = util.pythonise(value['id'])
            updated = steps[pipe_id] if steps else Id('pipe_%s' % pipe_id)
            yield ('embed', updated)

        # set splits in the pykwargs if this is split module
        if module_type == 'split':
            filtered = filter(
                lambda x: module_id == util.pythonise(x[1]['src']['moduleid']),
                pipe['wires'].items()
            )

            count = len(filtered)
            updated = count if steps else Id(count)
            yield ('splits', updated)


def _get_input_module(pipe, module_id, steps):
    input_module = steps['forever'] if steps else 'forever'

    if module_id in pipe['embed']:
        input_module = '_INPUT'
    else:
        for key, pipe_wire in pipe['wires'].items():
            moduleid = util.pythonise(pipe_wire['src']['moduleid'])

            # todo? this equates the outputs
            is_default_in_and_out = (
                util.pythonise(pipe_wire['tgt']['moduleid']) == module_id
                and pipe_wire['tgt']['id'] == '_INPUT'
                and pipe_wire['src']['id'].startswith('_OUTPUT')
            )

            # if the wire is to this module and it's the default input and it's
            # the default output:
            if is_default_in_and_out:
                input_module = steps[moduleid] if steps else moduleid
                break

    return input_module


def parse_pipe_def(pipe_def, pipe_name='anonymous'):
    """Parse pipe JSON into internal structures

    Keyword arguments:
    pipe_def -- JSON representation of the pipe
    pipe_name -- a name for the pipe (used for linking pipes)

    Returns:
    pipe -- an internal representation of a pipe
    """
    graph = defaultdict(list, util.gen_graph1(pipe_def))
    [graph[k].append(v) for k, v in util.gen_graph2(pipe_def)]
    modules = dict(util.gen_modules(pipe_def))
    embed = dict(util.gen_embedded_modules(pipe_def))
    modules.update(embed)

    return {
        'name': util.pythonise(pipe_name),
        'modules': modules,
        'embed': embed,
        'graph': dict(util.gen_graph3(graph)),
        'wires': dict(util.gen_wires(pipe_def)),
    }


def build_pipeline(context, pipe, pipe_def):
    """Convert a pipe into an executable Python pipeline

        If context.describe_input or context.describe_dependencies then just
        return that instead of the pipeline

        Note: any subpipes must be available to import from pipe2py.pypipelines
    """
    module_ids = topological_sort(pipe['graph'])
    pydeps = util.extract_dependencies(pipe_def)
    pyinput = util.extract_input(pipe_def)

    if not (context.describe_input or context.describe_dependencies):
        kwargs = {
            'module_ids': module_ids,
            'module_names': util.gen_names(module_ids, pipe),
            'pipe_names': util.gen_names(module_ids, pipe, 'pipe'),
        }

        zipped = _get_zipped(context, pipe, **kwargs)
        steps = _get_steps(context, pipe, zipped)

    if context.describe_input and context.describe_dependencies:
        pipeline = [{'inputs': pyinput, 'dependencies': pydeps}]
    elif context.describe_input:
        pipeline = pyinput
    elif context.describe_dependencies:
        pipeline = pydeps
    else:
        pipeline = steps[module_ids[-1]]

    for i in pipeline:
        yield i


def stringify_pipe(context, pipe, pipe_def):
    """Convert a pipe into Python script
    """
    module_ids = topological_sort(pipe['graph'])

    kwargs = {
        'module_ids': module_ids,
        'module_names': util.gen_names(module_ids, pipe),
        'pipe_names': util.gen_names(module_ids, pipe, 'pipe'),
    }

    zipped = _get_zipped(context, pipe, **kwargs)
    modules = list(_gen_string_modules(context, pipe, zipped))
    pydeps = util.extract_dependencies(pipe_def)
    pyinput = util.extract_input(pipe_def)
    env = Environment(loader=PackageLoader('pipe2py'))
    template = env.get_template('pypipe.txt')

    tmpl_kwargs = {
        'modules': modules,
        'pipe_name': pipe['name'],
        'inputs': unicode(pyinput),
        'dependencies': unicode(pydeps),
        'embedded_pipes': pipe['embed'],
        'last_module': module_ids[-1],
    }

    return template.render(**tmpl_kwargs)


if __name__ == '__main__':
    usage = 'usage: %prog [options] [filename]'
    parser = OptionParser(usage=usage)

    parser.add_option(
        "-p", "--pipe", dest="pipeid", help="read pipe JSON from Yahoo")
    parser.add_option(
        "-c", "--compiledpath", dest="compiledpath",
        help="the compiled pipe file destination path")
    parser.add_option(
        "-s", dest="savejson", help="save pipe JSON to file",
        action="store_true")
    parser.add_option(
        "-o", dest="saveoutput", help="save output from pipes.yahoo.com to file",
        action="store_true")
    parser.add_option(
        "-v", dest="verbose", help="set verbose debug", action="store_true")
    (options, args) = parser.parse_args()

    pipe_file_name = args[0] if args else None

    kwargs = {
        'describe_input': True,
        'describe_dependencies': True,
        'verbose': options.verbose,
    }

    context = Context(**kwargs)

    if options.pipeid:
        pipe_name = 'pipe_%s' % options.pipeid

        # Get the pipeline definition
        base = 'http://query.yahooapis.com/v1/public/yql?q='
        select = 'select%20PIPE.working%20from%20json%20'
        where = 'where%20url=%22http%3A%2F%2Fpipes.yahoo.com'
        pipe = '%2Fpipes%2Fpipe.info%3F_out=json%26_id=%s' % options.pipeid
        end = '%22&format=json'
        url = base + select + where + pipe + end
        # todo: refactor this url->json

        pjson = requests.get(url).text
        pipe_raw = _load_json(pjson)
        results = pipe_raw['query']['results']

        if not results:
            print('Pipe not found')
            sys.exit(1)

        pipe_def = results['json']['PIPE']['working']
    elif pipe_file_name:
        pipe_name = p.splitext(p.split(pipe_file_name)[-1])[0]

        with open(pipe_file_name) as f:
            pjson = f.read()

        pipe_def = _load_json(pjson)
    else:
        pipe_name = 'anonymous'
        pjson = ''.join(line for line in fileinput.input())
        pipe_def = _load_json(pjson)

    pipe = parse_pipe_def(pipe_def, pipe_name)
    new_path = p.join(PARENT, 'pypipelines', '%s.py' % pipe_name)
    path = options.compiledpath or new_path
    data = stringify_pipe(context, pipe, pipe_def)
    size = write_file(data, path)

    if context and context.verbose:
        print('wrote %i bytes to %s' % (size, path))

    if context and context.verbose:
        pydeps = util.extract_dependencies(pipe_def)
        print('Modules used in %s: %s' % (pipe['name'], pydeps))

    if options.savejson:
        path = p.join(PARENT, 'pipelines', '%s.json' % pipe_name)
        size = write_file(pipe_def, path, True)

        if context and context.verbose:
            print('wrote %i bytes to %s' % (size, path))

    if options.saveoutput:
        base = 'http://pipes.yahoo.com/pipes/pipe.run'
        url = '%s?_id=%s&_render=json' % (base, options.pipeid)
        ojson = requests.get(url).text
        pipe_output = _load_json(ojson)
        count = pipe_output['count']

        if not count:
            print('Pipe results not found')
            sys.exit(1)

        path = p.join(PARENT, 'data', '%s_output.json' % pipe_name)
        size = write_file(pipe_output, path, True)

        if context and context.verbose:
            print('wrote %i bytes to %s' % (size, path))

    # for build example - see test/testbasics.py

    # todo: to create stable, repeatable test cases we should:
    #  build the pipeline to find the external data sources
    #  download and save any fetchdata/fetch source data
