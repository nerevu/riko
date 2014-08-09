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
        pipeline = build_pipeline(self.context, pipe))

        for i in pipeline:
            print i

    Instead of passing a filename, a pipe id can be passed (-p) to fetch the
    JSON from Yahoo, e.g.

        python compile.py -p 2de0e4517ed76082dcddf66f7b218057

    Author: Greg Gaughan
    Idea: Tony Hirst (http://ouseful.wordpress.com/2010/02/25/starting-to-think-about-a-yahoo-pipes-code-generator)
    Python generator pipelines inspired by:
        David Beazely (http://www.dabeaz.com/generators-uk)
    Universal Feed Parser and auto-rss modules by:
        Mark Pilgrim (http://feedparser.org)

   License: see LICENSE file
"""
import fileinput
import urllib
import sys

from itertools import chain
from importlib import import_module
from jinja2 import Environment, PackageLoader
from optparse import OptionParser
from os.path import splitext, split
from pipe2py import Context, util
from pipe2py.pprint2 import Id, repr_args, str_args
from pipe2py.topsort import topological_sort
from pipe2py.modules import pipeforever


def _pipe_commons(context, pipe, module_id, pyinput=None, steps=None):
    pyinput = pyinput or []
    module = pipe['modules'][module_id]
    module_type = module['type']
    conf = module['conf']
    kwargs = {'conf': conf}
    output = None

    if module_type.startswith('pipe:'):
        # Import any required sub-pipelines and user inputs
        # Note: assumes they have already been compiled to accessible .py files
        import_module(util.pythonise(module_type)) if steps else None
        pythonised_type = util.pythonise(module_type)
        pymodule_name = '%s' % pythonised_type
        pymodule_generator = '%s' % pythonised_type
    else:
        pymodule_name = 'pipe%s' % module_type
        pymodule_generator = 'pipe_%s' % module_type

    if context.describe_input or not steps:
        # Find any required subpipelines and user inputs
        if conf and 'prompt' in conf:
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

        if steps:
            output = {
                'pyinput': pyinput,
                'pymodule_name': pymodule_name,
                'pymodule_generator': pymodule_generator,
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
            'pymodule_name': pymodule_name,
            'pymodule_generator': pymodule_generator,
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

    modules = pipe_def['modules']

    if not isinstance(modules, list):
        modules = [modules]

    for module in modules:
        pipe['modules'][util.pythonise(module['id'])] = module
        pipe['graph'][util.pythonise(module['id'])] = []
        module_type = module['type']

        if module_type == 'loop':
            embed = module['conf']['embed']['value']
            pipe['modules'][util.pythonise(embed['id'])] = embed
            pipe['graph'][util.pythonise(embed['id'])] = []
            pipe['embed'][util.pythonise(embed['id'])] = embed

            # make the loop dependent on its embedded module
            pipe['graph'][util.pythonise(embed['id'])].append(
                util.pythonise(module['id']))

    wires = pipe_def['wires']

    if not isinstance(wires, list):
        wires = [wires]

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

        If context.describe_input then just return the input requirements
        instead of the pipeline

        Note: any subpipes must be available to import as .py files current
        namespace can become polluted by submodule wrapper definitions
    """
    pyinput = None
    steps = {'forever': pipeforever.pipe_forever(context, None, conf=None)}

    for module_id in topological_sort(pipe['graph']):
        commons = _pipe_commons(context, pipe, module_id, pyinput, steps)
        pymodule_name = commons['pymodule_name']
        pymodule_generator = commons['pymodule_generator']
        pyinput = commons['pyinput']

        if context.describe_input:
            continue

        args = commons['args']
        kwargs = commons['kwargs']

        if pymodule_name.startswith('pipe_'):
            import_name = pymodule_name
        else:
            import_name = 'pipe2py.modules.%s' % pymodule_name

        module = import_module(import_name)
        generator = getattr(module, pymodule_generator)

        # if this module is an embedded module:
        if module_id in pipe['embed']:
            # We need to wrap submodules (used by loops) so we can pass the
            # input at runtime (as we can to sub-pipelines)
            # Note: no embed (so no subloops) or wire kwargs are
            # passed and outer_kwargs are passed in
            generator.__name__ = 'pipe_%s' % module_id
            steps[module_id] = generator
        else:  # else this module is not an embedded module:
            steps[module_id] = generator(*args, **kwargs)

        if context.verbose:
            print '%s (%s) = %s(%s)' % (
                steps[module_id], module_id, generator, str(args))

    if context.describe_input:
        pipeline = sorted(pyinput)
    else:
        pipeline = steps[module_id]

    return pipeline


def stringify_pipe(context, pipe):
    """Convert a pipe into Python script

       If context.describe_input is passed to the script then it just
       returns the input requirements instead of the pipeline
    """
    modules = []
    pyinput = None

    for module_id in topological_sort(pipe['graph']):
        module = {}

        commons = _pipe_commons(context, pipe, module_id, pyinput)
        pyinput = commons['pyinput']
        pymodule_generator = commons['pymodule_generator']
        pymodule_name = commons['pymodule_name']
        args = commons['args']
        kwargs = commons['kwargs']

        module['args'] = repr_args(chain(args, kwargs.items()))
        module['id'] = module_id
        module['pymodule_name'] = pymodule_name
        module['pymodule_generator'] = pymodule_generator
        modules.append(module)

        if context.verbose:
            con_args = filter(lambda x: x != Id('context'), args)
            nconf_kwargs = filter(lambda x: x[0] != 'conf', kwargs.items())
            conf_kwargs = filter(lambda x: x[0] == 'conf', kwargs.items())
            all_args = chain(con_args, nconf_kwargs, conf_kwargs)

            print (
                '%s = %s(%s)' % (
                    module_id, pymodule_generator, str_args(all_args)
                )
            ).encode('utf-8')

    env = Environment(loader=PackageLoader('pipe2py'))
    template = env.get_template('pypipe.txt')

    tmpl_kwargs = {
        'modules': modules,
        'pipe_name': pipe['name'],
        'inputs': unicode(sorted(pyinput)),
        'embedded_pipes': pipe['embed'],
        'last_module': module_id,
    }

    return template.render(**tmpl_kwargs)


def analyze_pipe(context, pipe):
    modules = set(module['type'] for module in pipe['modules'].values())
    moduletypes = sorted(list(modules))

    if context.verbose:
        print
        print 'Modules used:', ', '.join(
            name for name in moduletypes if not name.startswith('pipe:')
        ) or None

        print 'Other pipes used:', ', '.join(
            name[5:] for name in moduletypes if name.startswith('pipe:')
        ) or None

if __name__ == '__main__':
    try:
        import json
        json.loads  # test access to the attributes of the right json module
    except (ImportError, AttributeError):
        import simplejson as json

    usage = 'usage: %prog [options] [filename]'
    parser = OptionParser(usage=usage)

    parser.add_option(
        "-p", "--pipe", dest="pipeid", help="read pipe JSON from Yahoo",
        metavar="PIPEID")
    parser.add_option(
        "-s", dest="savejson", help="save pipe JSON to file",
        action="store_true")
    parser.add_option(
        "-v", dest="verbose", help="set verbose debug", action="store_true")
    (options, args) = parser.parse_args()

    filename = args[0] if args else None
    context = Context(verbose=options.verbose)

    if options.pipeid:
        base = 'http://query.yahooapis.com/v1/public/yql?q='
        select = 'select%20PIPE.working%20from%20json%20'
        where = 'where%20url%3D%22http%3A%2F%2Fpipes.yahoo.com'
        pipe = '%2Fpipes%2Fpipe.info%3F_out%3Djson%26_id%3D'
        end = '%22&format=json'
        url = base + select + where + pipe + options.pipeid + end

        src = ''.join(urllib.urlopen(url).readlines())
        src_json = json.loads(src)
        results = src_json['query']['results']

        if not results:
            print 'Pipe not found'
            sys.exit(1)

        pjson = results['json']['PIPE']['working']
        pipe_name = 'pipe_%s' % options.pipeid
    elif filename:
        pjson = ''.join(line for line in open(filename))
        pipe_name = splitext(split(filename)[-1])[0]
    else:
        pjson = ''.join(line for line in fileinput.input())
        pipe_name = 'anonymous'

    pipe_def = json.loads(pjson)
    pipe = parse_pipe_def(pipe_def, pipe_name)

    if options.savejson:
        with open('%s.json' % pipe_name, 'w') as f:
            pprint(json.loads(pjson.encode('utf-8')), f)

    with open('%s.py' % pipe_name, 'w') as f:
        f.write(stringify_pipe(context, pipe))

    analyze_pipe(context, pipe)

    # for build example - see test/testbasics.py
