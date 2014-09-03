"""Compile/Translate Yahoo Pipe into Python

    Takes a JSON representation of a Yahoo pipe and either:
     a) translates it into a Python script containing a function
        (using generators to build the pipeline) or
     b) compiles it as a pipeline of generators which can be executed
        in-process

    Usage:
     a) python compile.py pipe1.json
        python pipe1.py

     b) from pipe2py import compile, Context

        pipe_def = json.loads(pjson)
        pipe = parse_pipe_def(pipe_def, pipe_name)
        pipeline = build_pipeline(Context(), pipe))

        for i in pipeline:
            print i

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
from itertools import chain
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

            f.write(data)


def _load_json(json):
    try:
        loaded = loads(json.encode('utf-8'))
    except UnicodeDecodeError:
        loaded = loads(json)

    return loaded




def _gen_string_modules(context, pipe, pyinput):
    for module_id in topological_sort(pipe['graph']):
        commons = _pipe_commons(context, pipe, module_id, pyinput)
        pyinput = commons['pyinput']
        pipe_name = commons['pipe_name']
        module_name = commons['module_name']
        args = commons['args']
        kwargs = commons['kwargs']

        if context and context.verbose:
            con_args = filter(lambda x: x != Id('context'), args)
            nconf_kwargs = filter(lambda x: x[0] != 'conf', kwargs.items())
            conf_kwargs = filter(lambda x: x[0] == 'conf', kwargs.items())
            all_args = chain(con_args, nconf_kwargs, conf_kwargs)

            print (
                '%s = %s(%s)' % (
                    module_id, pipe_name, str_args(all_args)
                )
            ).encode('utf-8')

        yield {
            'args': repr_args(chain(args, kwargs.items())),
            'id': module_id,
            'sub_pipe': module_name.startswith('pipe_'),
            'name': module_name,
            'pipe_name': pipe_name,
            'pyinput': pyinput,
        }


def _pipe_commons(context, pipe, module_id, pyinput=None, steps=None):
    pyinput = pyinput or []
    module = pipe['modules'][module_id]
    module_type = module['type']
    conf = module['conf']
    kwargs = {'conf': conf}
    output = None

    if module_type.startswith('pipe:'):
        pythonised_type = util.pythonise(module_type)
        module_name = pythonised_type
        pipe_name = pythonised_type
    else:
        module_name = 'pipe%s' % module_type
        pipe_name = 'pipe_%s' % module_type

    if context.describe_input or context.describe_dependencies or not steps:
        # Find any required subpipelines and user inputs
        if context.describe_input and conf and 'prompt' in conf:
            # Note: there seems to be no need to recursively collate inputs
            # from subpipelines
            module_confs = (
                module['conf']['position']['value'],
                module['conf']['name']['value'],
                module['conf']['prompt']['value'],
                module['conf']['default']['type'],
                module['conf']['default']['value']
            )

            pyinput.append(module_confs)
        elif context.describe_dependencies:
            if 'embed' in module['conf']:
                pyinput.append(module['conf']['embed']['value']['type'])

            pyinput.append(module_name)

        if steps:
            output = {
                'pyinput': pyinput,
                'module_name': module_name,
                'pipe_name': pipe_name,
            }

    if not output:
        # find the default input of this module
        input_module = steps['forever'] if steps else 'forever'

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

            # todo? this equates the outputs
            is_default_out_only = (
                util.pythonise(pipe_wire['tgt']['moduleid']) == module_id
                and pipe_wire['tgt']['id'] != '_INPUT'
                and pipe_wire['src']['id'].startswith('_OUTPUT')
            )

            # if the wire is to this module and it's *NOT* the default input
            # and it's the default output
            if is_default_out_only:
                # set the extra inputs of this module as kwargs of this module
                pipe_id = util.pythonise(pipe_wire['tgt']['id'])
                updated = steps[moduleid] if steps else Id(moduleid)
                kwargs.update({pipe_id: updated})

        if module_id in pipe['embed']:
            text = 'input_module of an embedded module was already set'
            # what is this for???
            # assert input_module == (steps['forever'], text)
            input_module = '_INPUT'

        args = [context, input_module] if steps else [
            Id('context'), Id(input_module)]

        # set the embedded module in the kwargs if this is loop module
        if module_type == 'loop':
            value = module['conf']['embed']['value']
            pipe_id = util.pythonise(value['id'])
            updated = steps[pipe_id] if steps else Id('pipe_%s' % pipe_id)
            kwargs.update({'embed': updated})

        # set splits in the kwargs if this is split module
        if module_type == 'split':
            filtered = filter(
                lambda x: module_id == util.pythonise(x[1]['src']['moduleid']),
                pipe['wires'].items()
            )

            count = len(filtered)
            updated = count if steps else Id(count)
            kwargs.update({'splits': updated})

        output = {
            'pyinput': pyinput,
            'module_name': module_name,
            'pipe_name': pipe_name,
            'args': args,
            'kwargs': kwargs,
        }

    return output


def parse_pipe_def(pipe_def, pipe_name='anonymous'):
    """Parse pipe JSON into internal structures

    Keyword arguments:
    pipe_def -- JSON representation of the pipe
    pipe_name -- a name for the pipe (used for linking pipes)

    Returns:
    pipe -- an internal representation of a pipe
    """
    pipe = {
        'name': util.pythonise(pipe_name),
        'modules': {},
        'embed': {},
        'graph': {},
        'wires': {},
    }

    modules = util.listize(pipe_def['modules'])

    for module in modules:
        module_id = util.pythonise(module['id'])
        pipe['modules'][module_id] = module
        pipe['graph'][module_id] = []
        module_type = module['type']

        if module_type == 'loop':
            embed = module['conf']['embed']['value']
            embed_id = util.pythonise(embed['id'])
            pipe['modules'][embed_id] = embed
            pipe['graph'][embed_id] = []
            pipe['embed'][embed_id] = embed

            # make the loop dependent on its embedded module
            pipe['graph'][embed_id].append(module_id)

    wires = util.listize(pipe_def['wires'])

    for wire in wires:
        pipe['wires'][util.pythonise(wire['id'])] = wire
        pipe['graph'][util.pythonise(wire['src']['moduleid'])].append(
            util.pythonise(wire['tgt']['moduleid']))

    # Remove any orphan nodes
    for node in pipe['graph'].keys():
        targetted = [node in value for key, value in pipe['graph'].items()]

        if not pipe['graph'][node] and not any(targetted):
            del pipe['graph'][node]

    return pipe


def build_pipeline(context, pipe):
    """Convert a pipe into an executable Python pipeline

        If context.describe_input or context.describe_dependencies then just
        return that instead of the pipeline

        Note: any subpipes must be available to import as .py files current
        namespace can become polluted by submodule wrapper definitions
    """
    pyinput = None
    steps = {'forever': pipe_forever()}

    for module_id in topological_sort(pipe['graph']):
        commons = _pipe_commons(context, pipe, module_id, pyinput, steps)
        module_name = commons['module_name']
        pipe_name = commons['pipe_name']
        pyinput = commons['pyinput']

        if context.describe_input or context.describe_dependencies:
            continue

        args = commons['args']
        kwargs = commons['kwargs']

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
            # Note: no embed (so no subloops) or wire kwargs are
            # passed and outer_kwargs are passed in
            pipe_generator.__name__ = str('pipe_%s' % module_id)
            steps[module_id] = pipe_generator
        else:  # else this module is not an embedded module:
            steps[module_id] = pipe_generator(*args, **kwargs)

        if context and context.verbose:
            print(
                '%s (%s) = %s(%s)' % (
                    steps[module_id], module_id, pipe_generator, str(args)))

    if context.describe_input or context.describe_dependencies:
        pipeline = sorted(set(pyinput))
    else:
        pipeline = steps[module_id]

    return pipeline


def stringify_pipe(context, pipe):
    """Convert a pipe into Python script

       If context.describe_input or context.describe_dependencies is passed to
       the script then it just returns that instead of the pipeline
    """
    modules = list(_gen_string_modules(context, pipe, None))
    env = Environment(loader=PackageLoader('pipe2py'))
    template = env.get_template('pypipe.txt')

    tmpl_kwargs = {
        'modules': modules,
        'pipe_name': pipe['name'],
        'inputs': unicode(sorted(modules[-1]['pyinput'])),
        'embedded_pipes': pipe['embed'],
        'last_module': modules[-1]['id'],
    }

    return template.render(**tmpl_kwargs)


def analyze_pipe(context, pipe):
    modules = set(module['type'] for module in pipe['modules'].values())
    moduletypes = sorted(list(modules))

    if context and context.verbose:
        filtered = filter(lambda x: not x.startswith('pipe:'), moduletypes)
        pipes = filter(lambda x: x.startswith('pipe:'), moduletypes)
        print('Modules used:', ', '.join(filtered) or None)
        print('Other pipes used:', ', '.join(x[5:] for x in pipes) or None)


if __name__ == '__main__':
    usage = 'usage: %prog [options] [filename]'
    parser = OptionParser(usage=usage)

    parser.add_option(
        "-p", "--pipe", dest="pipeid", help="read pipe JSON from Yahoo",
        metavar="PIPEID")
    parser.add_option(
        "-s", dest="savejson", help="save pipe JSON to file",
        action="store_true")
    parser.add_option(
        "-o", dest="saveoutput", help="save pipe output to file",
        action="store_true")
    parser.add_option(
        "-v", dest="verbose", help="set verbose debug", action="store_true")
    (options, args) = parser.parse_args()

    pipe_file_name = args[0] if args else None
    context = Context(verbose=options.verbose)

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
    path = p.join(PARENT, 'pypipelines', '%s.py' % pipe_name)
    data = stringify_pipe(context, pipe)
    write_file(data, path)
    analyze_pipe(context, pipe)

    if options.savejson:
        path = p.join(PARENT, 'pipelines', '%s.json' % pipe_name)
        write_file(pipe_def, path, True)

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
        write_file(pipe_output, path, True)

    # for build example - see test/testbasics.py

    # todo: to create stable, repeatable test cases we should:
    #  build the pipeline to find the external data sources
    #  download and save any fetchdata/fetch source data
