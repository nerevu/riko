"""Compile/Translate Yahoo Pipe into Python

   Takes a JSON representation of a Yahoo pipe and either:

     a) translates it into a Python script containing a function (using generators to build the pipeline)
     or
     b) compiles it as a pipeline of generators which can be executed in-process

   Usage:
     a) python compile.py pipe1.json
        python pipe1.py

     b) from pipe2py import compile, Context
        p = compile.parse_and_build_pipe(Context(), "JSON pipe representation")
        for i in p:
            print i

   Instead of passing a filename, a pipe id can be passed (-p) to fetch the JSON from Yahoo, e.g.
       python compile.py -p 2de0e4517ed76082dcddf66f7b218057

   Author: Greg Gaughan
   Idea: Tony Hirst (http://ouseful.wordpress.com/2010/02/25/starting-to-think-about-a-yahoo-pipes-code-generator)
   Python generator pipelines inspired by: David Beazely (http://www.dabeaz.com/generators-uk)
   Universal Feed Parser and autorss modules by: Mark Pilgrim (http://feedparser.org)

   Licence: see LICENCE file
"""

__version__ = "0.9.5"

from optparse import OptionParser
import fileinput
import urllib
import os
import sys

from pipe2py import Context
from pipe2py import util
from pipe2py.pprint import Id, repr_args, repr_arg, str_args, str_arg

from topsort import topological_sort

#needed for build_pipe - ensure modules/__init__.py.__all__ lists all available modules
from pipe2py.modules import *


try:
    import wingdbstub
except:
    pass

def _parse_pipe(json_pipe, pipe_name="anonymous"):
    """Parse pipe JSON into internal structures

    Keyword arguments:
    json_pipe -- JSON representation of the pipe
    pipe_name -- a name for the pipe (used for linking pipes)

    Returns:
    pipe -- an internal representation of a pipe
    """
    pipe = {'name': util.pythonise(pipe_name)}

    pipe['modules'] = {}
    pipe['embed'] = {}
    pipe['graph'] = {}
    pipe['wires'] = {}
    modules = json_pipe['modules']
    if not isinstance(modules, list):
        modules = [modules]
    for module in modules:
        pipe['modules'][util.pythonise(module['id'])] = module
        pipe['graph'][util.pythonise(module['id'])] = []
        if module['type'] == 'loop':
            embed = module['conf']['embed']['value']
            pipe['modules'][util.pythonise(embed['id'])] = embed
            pipe['graph'][util.pythonise(embed['id'])] = []
            pipe['embed'][util.pythonise(embed['id'])] = embed
            #make the loop dependent on its embedded module
            pipe['graph'][util.pythonise(embed['id'])].append(util.pythonise(module['id']))

    wires = json_pipe['wires']
    if not isinstance(wires, list):
        wires = [wires]
    for wire in wires:
        pipe['graph'][util.pythonise(wire['src']['moduleid'])].append(util.pythonise(wire['tgt']['moduleid']))

    #Remove any orphan nodes
    for node in pipe['graph'].keys():
        targetted = [node in pipe['graph'][k] for k in pipe['graph']]
        if not pipe['graph'][node] and not any(targetted):
            del pipe['graph'][node]

    for wire in wires:
        pipe['wires'][util.pythonise(wire['id'])] = wire

    return pipe

def build_pipe(context, pipe):
    """Convert a pipe into an executable Python pipeline

       If context.describe_input then just return the input requirements instead of the pipeline

       Note: any subpipes must be available to import as .py files
             current namespace can become polluted by submodule wrapper definitions
    """
    pyinput = []

    module_sequence = topological_sort(pipe['graph'])

    #First pass to find and import any required subpipelines and user inputs
    #Note: assumes they have already been compiled to accessible .py files
    for module_id in module_sequence:
        module = pipe['modules'][module_id]
        if module['type'].startswith('pipe:'):
            __import__(util.pythonise(module['type']))
        if module['conf'] and 'prompt' in module['conf'] and context.describe_input:
            pyinput.append((module['conf']['position']['value'],
                            module['conf']['name']['value'],
                            module['conf']['prompt']['value'],
                            module['conf']['default']['type'],
                            module['conf']['default']['value']))
            #Note: there seems to be no need to recursively collate inputs from subpipelines

    if context.describe_input:
        return sorted(pyinput)

    steps = {}
    steps["forever"] = pipeforever.pipe_forever(context, None, conf=None)
    for module_id in module_sequence:
        module = pipe['modules'][module_id]

        #Plumb I/O

        # find the default input of this module
        input_module = steps["forever"]
        for wire in pipe['wires']:
            # if the wire is to this module and it's the default input and it's the default output:
            if util.pythonise(pipe['wires'][wire]['tgt']['moduleid']) == module_id and pipe['wires'][wire]['tgt']['id'] == '_INPUT' and pipe['wires'][wire]['src']['id'].startswith('_OUTPUT'): # todo? this equates the outputs
                input_module = steps[util.pythonise(pipe['wires'][wire]['src']['moduleid'])]

        if module_id in pipe['embed']:
            assert input_module == steps["forever"], "input_module of an embedded module was already set"
            input_module = "_INPUT"

        pargs = [context,
                 input_module,
                ]
        kargs = {"conf":module['conf'],
                }

        # set the extra inputs of this module as kargs of this module
        for wire in pipe['wires']:
            # if the wire is to this module and it's *not* the default input and it's the default output:
            if util.pythonise(pipe['wires'][wire]['tgt']['moduleid']) == module_id and pipe['wires'][wire]['tgt']['id'] != '_INPUT' and pipe['wires'][wire]['src']['id'].startswith('_OUTPUT'): # todo? this equates the outputs
                kargs["%(id)s" % {'id':util.pythonise(pipe['wires'][wire]['tgt']['id'])}] = steps[util.pythonise(pipe['wires'][wire]['src']['moduleid'])]

        # set the embedded module in the kargs if this is loop module
        if module['type'] == 'loop':
            kargs["embed"] = steps[util.pythonise(module['conf']['embed']['value']['id'])]

        if module['type'] == 'split':
            kargs["splits"] = len([1 for w in pipe['wires'] if util.pythonise(pipe['wires'][w]['src']['moduleid']) == module_id])

        #todo (re)import other pipes dynamically
        pymodule_name = "pipe%(module_type)s" % {'module_type':module['type']}
        pymodule_generator_name = "pipe_%(module_type)s" % {'module_type':module['type']}
        if module['type'].startswith('pipe:'):
            pymodule_name = "sys.modules['%(module_type)s']" % {'module_type':util.pythonise(module['type'])}
            pymodule_generator_name = "%(module_type)s" % {'module_type':util.pythonise(module['type'])}

        # if this module is an embedded module:
        if module_id in pipe['embed']:
            #We need to wrap submodules (used by loops) so we can pass the input at runtime (as we can to subpipelines)
            pypipe = ("""def pipe_%(module_id)s(context, _INPUT, conf=None, **kwargs):\n"""
                      """    return %(pymodule_name)s.%(pymodule_generator_name)s(context, _INPUT, conf=%(conf)s, **kwargs)\n"""
                       % {'module_id':module_id,
                          'pymodule_name':pymodule_name,
                          'pymodule_generator_name':pymodule_generator_name,
                          'conf':module['conf'],
                          #Note: no embed (so no subloops) or wire kargs are passed and outer kwargs are passed in
                         }
                     )
            exec pypipe   #Note: evaluated in current namespace - todo ok?
            steps[module_id] = eval("pipe_%(module_id)s" % {'module_id':module_id})
        else: # else this module is not an embedded module:
            module_ref = eval("%(pymodule_name)s.%(pymodule_generator_name)s" % {'pymodule_name':pymodule_name,
                                                                                 'pymodule_generator_name':pymodule_generator_name,})
            steps[module_id] = module_ref(*pargs, **kargs)

        if context.verbose:
            print "%s (%s) = %s(%s)" %(steps[module_id], module_id, module_ref, str(pargs))

    return steps[module_id]


def write_pipe(context, pipe):
    """Convert a pipe into Python script

       If context.describe_input is passed to the script then it just returns the input requirements instead of the pipeline
    """

    pypipe = ("""#Pipe %(pipename)s generated by pipe2py\n"""
              """\n"""
              """from pipe2py import Context\n"""
              """from pipe2py.modules import *\n"""
              """\n""" % {'pipename':pipe['name']}
             )
    pyinput = []

    module_sequence = topological_sort(pipe['graph'])

    #First pass to find any required subpipelines and user inputs
    for module_id in module_sequence:
        module = pipe['modules'][module_id]
        if module['type'].startswith('pipe:'):
            pypipe += """import %(module_type)s\n""" % {'module_type':util.pythonise(module['type'])}
        if module['conf'] and 'prompt' in module['conf']:
            pyinput.append((module['conf']['position']['value'],
                            module['conf']['name']['value'],
                            module['conf']['prompt']['value'],
                            module['conf']['default']['type'],
                            module['conf']['default']['value']))
            #Note: there seems to be no need to recursively collate inputs from subpipelines

    pypipe += ("""\n"""
               """def %(pipename)s(context, _INPUT, conf=None, **kwargs):\n"""
               """    "Pipeline"\n"""     #todo insert pipeline description here
               """    if conf is None:\n"""
               """        conf = {}\n"""
               """\n"""
               """    if context.describe_input:\n"""
               """        return %(inputs)s\n"""
               """\n"""
               """    forever = pipeforever.pipe_forever(context, None, conf=None)\n"""
               """\n""" % {'pipename':pipe['name'],
                           'inputs':unicode(sorted(pyinput))}  #todo pprint this
              )

    prev_module = []
    for module_id in module_sequence:
        module = pipe['modules'][module_id]

        #Plumb I/O

        # find the default input of this module
        input_module = "forever"
        for wire in pipe['wires']:
            # if the wire is to this module and it's the default input and it's the default output:
            if util.pythonise(pipe['wires'][wire]['tgt']['moduleid']) == module_id and pipe['wires'][wire]['tgt']['id'] == '_INPUT' and pipe['wires'][wire]['src']['id'].startswith('_OUTPUT'): # todo? this equates the outputs
                input_module = util.pythonise(pipe['wires'][wire]['src']['moduleid'])

        if module_id in pipe['embed']:
            assert input_module == "forever", "input_module of an embedded module was already set"
            input_module = "_INPUT"

        mod_args = [Id('context'), Id(input_module)]
        mod_kwargs = [('conf', module['conf'])]

        # set the extra inputs of this module as kwargs of this module
        for wire in pipe['wires']:
            # if the wire is to this module and it's *not* the default input and it's the default output:
            if util.pythonise(pipe['wires'][wire]['tgt']['moduleid']) == module_id and pipe['wires'][wire]['tgt']['id'] != '_INPUT' and pipe['wires'][wire]['src']['id'].startswith('_OUTPUT'): # todo? this equates the outputs
                mod_kwargs += [(util.pythonise(pipe['wires'][wire]['tgt']['id']), Id(util.pythonise(pipe['wires'][wire]['src']['moduleid'])))]

        # set the embedded module in the kwargs if this is loop module
        if module['type'] == 'loop':
            mod_kwargs += [("embed", Id("pipe_%s" % util.pythonise(module['conf']['embed']['value']['id'])))]

        # set splits in the kwargs if this is split module
        if module['type'] == 'split':
            mod_kwargs += [("splits", Id(len([1 for w in pipe['wires'] if util.pythonise(pipe['wires'][w]['src']['moduleid']) == module_id])))]

        pymodule_name = "pipe%(module_type)s" % {'module_type':module['type']}
        pymodule_generator_name = "pipe_%(module_type)s" % {'module_type':module['type']}
        if module['type'].startswith('pipe:'):
            pymodule_name = "%(module_type)s" % {'module_type':util.pythonise(module['type'])}
            pymodule_generator_name = "%(module_type)s" % {'module_type':util.pythonise(module['type'])}

        indent = ""
        if module_id in pipe['embed']:
            #We need to wrap submodules (used by loops) so we can pass the input at runtime (as we can to subpipelines)
            pypipe += ("""    def pipe_%(module_id)s(context, _INPUT, conf=None, **kwargs):\n"""
                       """        "Submodule"\n"""     #todo insert submodule description here
                       % {'module_id':module_id}
                       )
            indent = "    "

        pypipe += """%(indent)s    %(module_id)s = %(pymodule_name)s.%(pymodule_generator_name)s(%(pargs)s)\n""" % {
                                                 'indent':indent,
                                                 'module_id':module_id,
                                                 'pymodule_name':pymodule_name,
                                                 'pymodule_generator_name':pymodule_generator_name,
                                                 'pargs':repr_args(mod_args+mod_kwargs)}
        if module_id in pipe['embed']:
            pypipe += """        return %(module_id)s\n""" % {'module_id':module_id}

        prev_module = module_id

        if context.verbose:
            print ("%s = %s(%s)" % (module_id, pymodule_generator_name,
                                    str_args([arg for arg in mod_args if arg != Id('context')]+
                                             [(key, value) for key, value in mod_kwargs if key != 'conf']+
                                             [(key, value) for key, value in mod_kwargs if key == 'conf']))
                   ).encode("utf-8")

    pypipe += """    return %(module_id)s\n""" % {'module_id':prev_module}
    pypipe += ("""\n"""
               """if __name__ == "__main__":\n"""
               """    context = Context()\n"""
               """    p = %(pipename)s(context, None)\n"""
               """    for i in p:\n"""
               """        print i\n""" % {'pipename':pipe['name']}
              )

    return pypipe

def parse_and_write_pipe(context, json_pipe, pipe_name="anonymous"):
    pipe = _parse_pipe(json_pipe, pipe_name)
    pw = write_pipe(context, pipe)
    return pw

def parse_and_build_pipe(context, json_pipe, pipe_name="anonymous"):
    pipe = _parse_pipe(json_pipe, pipe_name)
    pb = build_pipe(context, pipe)
    return pb

def parse_and_analyze_pipe(context, json_pipe, pipe_name="anonymous"):
    pipe = _parse_pipe(json_pipe, pipe_name)
    moduletypes = sorted(list(set([module['type'] for module in pipe['modules'].values()])))
    if context.verbose:
        print
        print "Modules used:", ', '.join(name for name in moduletypes if not name.startswith("pipe:")) or None
        print "Other pipes used:", ', '.join(name[5:] for name in moduletypes if name.startswith("pipe:")) or None

if __name__ == '__main__':
    try:
        import json
        json.loads # test access to the attributes of the right json module
    except (ImportError, AttributeError):
        import simplejson as json

    context = Context()

    pjson = []

    usage = "usage: %prog [options] [filename]"
    parser = OptionParser(usage=usage)
    parser.add_option("-p", "--pipe", dest="pipeid",
                      help="read pipe JSON from Yahoo", metavar="PIPEID")
    parser.add_option("-s", dest="savejson",
                      help="save pipe JSON to file", action="store_true")
    parser.add_option("-v", dest="verbose",
                      help="set verbose debug", action="store_true")
    (options, args) = parser.parse_args()

    name = "anonymous"
    filename = None
    if len(args):
        filename = args[0]
    context.verbose = options.verbose
    if options.pipeid:
        url = ("""http://query.yahooapis.com/v1/public/yql"""
               """?q=select%20PIPE.working%20from%20json%20"""
               """where%20url%3D%22http%3A%2F%2Fpipes.yahoo.com%2Fpipes%2Fpipe.info%3F_out%3Djson%26_id%3D"""
               + options.pipeid +
               """%22&format=json""")
        pjson = urllib.urlopen(url).readlines()
        pjson = "".join(pjson)
        pipe_def = json.loads(pjson)
        if not pipe_def['query']['results']:
            print "Pipe not found"
            sys.exit(1)
        pjson = pipe_def['query']['results']['json']['PIPE']['working']
        if isinstance(pjson, str) or isinstance(pjson, unicode):
            pjson = json.loads(pjson)
        pipe_def = pjson
        pjson = json.dumps(pjson)  #was not needed until April 2011 - changes at Yahoo! Pipes/YQL?
        name = "pipe_%s" % options.pipeid
    elif filename:
        for line in fileinput.input(filename):
            pjson.append(line)
        pjson = "".join(pjson)
        pipe_def = json.loads(pjson)
        name = os.path.splitext(os.path.split(filename)[-1])[0]
    else:
        for line in fileinput.input():
            pjson.append(line)
        pjson = "".join(pjson)
        pipe_def = json.loads(pjson)

    if options.savejson:
        fj = open("%s.json" % name, "w")   #todo confirm file overwrite
        print >>fj, pjson.encode("utf-8")


    fp = open("%s.py" % name, "w")   #todo confirm file overwrite
    print >>fp, parse_and_write_pipe(context, pipe_def, name)

    parse_and_analyze_pipe(context, pipe_def, name)

    #for build example - see test/testbasics.py
