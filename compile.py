"""Compile/Translate Yahoo Pipe into Python

   Takes a JSON representation of a Yahoo pipe and either:
   
     a) translates it into a Python script containing a function (using generators to build the pipeline)
     or
     b) compile it as a pipeline of generators which can be executed in-process
     
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
           with modules added by: Tony Hirst
   Idea: Tony Hirst (http://ouseful.wordpress.com/2010/02/25/starting-to-think-about-a-yahoo-pipes-code-generator)
   Python generator pipelines inspired by: David Beazely (http://www.dabeaz.com/generators-uk)
"""

from optparse import OptionParser
import fileinput
import urllib
import os
import sys

from pipe2py import Context
from pipe2py import util

try:
    import json
except ImportError:
    import simplejson as json
   
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
    for module in json_pipe['modules']:
        pipe['modules'][util.pythonise(module['id'])] = module
        pipe['graph'][util.pythonise(module['id'])] = []
        if module['type'] == 'loop':
            embed = module['conf']['embed']['value']
            pipe['modules'][util.pythonise(embed['id'])] = embed
            pipe['graph'][util.pythonise(embed['id'])] = []
            pipe['embed'][util.pythonise(embed['id'])] = embed
            #make the loop dependent on its embedded module
            pipe['graph'][util.pythonise(embed['id'])].append(util.pythonise(module['id']))

    for wire in json_pipe['wires']:
        pipe['graph'][util.pythonise(wire['src']['moduleid'])].append(util.pythonise(wire['tgt']['moduleid']))

    for wire in json_pipe['wires']:
        pipe['wires'][util.pythonise(wire['id'])] = wire
            
    return pipe

def build_pipe(context, pipe):
    """Convert a pipe into an executable Python pipeline
    
       Note: any subpipes must be available to import as .py files
             current namespace can become polluted by submodule wrapper definitions
    """
    module_sequence = topological_sort(pipe['graph'])

    #First pass to find and import any required subpipelines
    #Note: assumes they have already been compiled to accessible .py files
    for module_id in module_sequence:
        module = pipe['modules'][module_id]
        if module['type'].startswith('pipe:'):
            __import__(util.pythonise(module['type']))
    
    steps = {}
    steps["forever"] = pipeforever.pipe_forever(context, None, conf=None)
    for module_id in module_sequence:
        module = pipe['modules'][module_id]
        
        #Plumb I/O
        input_module = steps["forever"]
        for wire in pipe['wires']:
            if util.pythonise(pipe['wires'][wire]['tgt']['moduleid']) == module_id and pipe['wires'][wire]['tgt']['id'] == '_INPUT' and pipe['wires'][wire]['src']['id'] == '_OUTPUT':
                input_module = steps[util.pythonise(pipe['wires'][wire]['src']['moduleid'])]

        if module_id in pipe['embed']:
            assert input_module == steps["forever"], "input_module of an embedded module was already set"
            input_module = "_INPUT"
                
        pargs = [context,
                 input_module,
                ]
        kargs = {"conf":module['conf'],
                }
            
        for wire in pipe['wires']:
            if util.pythonise(pipe['wires'][wire]['tgt']['moduleid']) == module_id and pipe['wires'][wire]['tgt']['id'] != '_INPUT' and pipe['wires'][wire]['src']['id'] == '_OUTPUT':
                kargs["%(id)s" % {'id':util.pythonise(pipe['wires'][wire]['tgt']['id'])}] = steps[util.pythonise(pipe['wires'][wire]['src']['moduleid'])]
                
        if module['type'] == 'loop':
            #todo need to hook up any inputs here
            kargs["embed"] = steps[util.pythonise(module['conf']['embed']['value']['id'])]
                
        #todo (re)import other pipes dynamically
        pymodule_name = "pipe%(module_type)s" % {'module_type':module['type']}
        pymodule_generator_name = "pipe_%(module_type)s" % {'module_type':module['type']}
        if module['type'].startswith('pipe:'):
            pymodule_name = "sys.modules['%(module_type)s']" % {'module_type':util.pythonise(module['type'])}
            pymodule_generator_name = "%(module_type)s" % {'module_type':util.pythonise(module['type'])}            
            
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
        else:
            module_ref = eval("%(pymodule_name)s.%(pymodule_generator_name)s" % {'pymodule_name':pymodule_name, 
                                                                                 'pymodule_generator_name':pymodule_generator_name,})
            steps[module_id] = module_ref(*pargs, **kargs)

        if context.verbose:
            print "%s (%s) = %s(%s)" %(steps[module_id], module_id, module_ref, str(pargs))

    return steps[module_id]
    
    
def write_pipe(context, pipe):
    """Convert a pipe into Python script
    """

    pypipe = ("""#Pipe %(pipename)s generated by pipe2py\n"""
              """\n"""
              """from pipe2py import Context\n"""
              """from pipe2py.modules import *\n"""
              """\n""" % {'pipename':pipe['name']}
             )
    
    module_sequence = topological_sort(pipe['graph'])
    
    #First pass to find any required subpipelines
    for module_id in module_sequence:
        module = pipe['modules'][module_id]
        if module['type'].startswith('pipe:'):
            pypipe += """import %(module_type)s\n""" % {'module_type':util.pythonise(module['type'])}
            
    pypipe += ("""\n"""
               """def %(pipename)s(context, _INPUT, conf=None, **kwargs):\n"""
               """    "Pipeline"\n"""     #todo insert pipeline description here
               """    if conf is None:\n"""
               """        conf = {}\n"""
               """\n"""
               """    forever = pipeforever.pipe_forever(context, None, conf=None)\n"""
               """\n""" % {'pipename':pipe['name']}
              )

    for module_id in module_sequence:
        module = pipe['modules'][module_id]

        #Plumb I/O
        input_module = "forever"
        for wire in pipe['wires']:
            if util.pythonise(pipe['wires'][wire]['tgt']['moduleid']) == module_id and pipe['wires'][wire]['tgt']['id'] == '_INPUT' and pipe['wires'][wire]['src']['id'] == '_OUTPUT':
                input_module = util.pythonise(pipe['wires'][wire]['src']['moduleid'])

        if module_id in pipe['embed']:
            assert input_module == "forever", "input_module of an embedded module was already set"
            input_module = "_INPUT"
        
        pargs = ["%(input_module)s" % {'input_module':input_module}, 
                 "conf=%(conf)s" % {'conf':module['conf']},
                ]
        
        for wire in pipe['wires']:
            if util.pythonise(pipe['wires'][wire]['tgt']['moduleid']) == module_id and pipe['wires'][wire]['tgt']['id'] != '_INPUT' and pipe['wires'][wire]['src']['id'] == '_OUTPUT':
                pargs.append("%(id)s = %(secondary_module)s" % {'id':util.pythonise(pipe['wires'][wire]['tgt']['id']), 'secondary_module':util.pythonise(pipe['wires'][wire]['src']['moduleid'])})
                
        if module['type'] == 'loop':
            pargs.append("embed = pipe_%(embed_module)s" % {'embed_module':util.pythonise(module['conf']['embed']['value']['id'])})
        
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
            
        pypipe += """%(indent)s    %(module_id)s = %(pymodule_name)s.%(pymodule_generator_name)s(context, %(pargs)s)\n""" % {
                                                 'indent':indent,
                                                 'module_id':module_id,
                                                 'pymodule_name':pymodule_name,
                                                 'pymodule_generator_name':pymodule_generator_name,
                                                 'pargs':", ".join(pargs)}
        if module_id in pipe['embed']:
            pypipe += """        return %(module_id)s\n""" % {'module_id':module_id}

        prev_module = module_id
        
        #todo? if context.verbose:
        #    print "%s = %s.%s(%s)" %(module_id, pymodule_name, pymodule_generator_name, str(pargs))
    
    pypipe += """    return _OUTPUT\n"""
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

if __name__ == '__main__':
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
        pjson = pipe_def['query']['results']['json']['PIPE']['working'] #todo note: I'm sure this needed wrapping in json.dumps() before
        pipe_def = json.loads(pjson)
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
        print >>fj, pjson
        
    
    fp = open("%s.py" % name, "w")   #todo confirm file overwrite
    print >>fp, parse_and_write_pipe(context, pipe_def, name)
    
    #for build example - see test/testbasics.py
