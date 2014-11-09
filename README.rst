A project to compile Yahoo! Pipes into Python
(see it hosted on Google App Engine: http://pipes-engine.appspot.com)

Design
======
Yahoo! Pipes are translated into Python generators (pipelines) which
should give a close match to the original data flow. Each call to the final
generator will ripple through the pipeline issuing `.next()` calls until the
source is exhausted.

The modules are topologically sorted to give their creation order.
The main output and inputs are connected via the yielded values and the
first parameter. Other inputs are passed as named parameters referencing the
input module.

The JSON representation of the configuration parameters maps closely onto
Python dictionaries and so is left as-is and passed and parsed as-and-when
needed.

Each Yahoo module is coded as a separate Python module. This might help in the
future if the generators are made to run on separate processors/machines and
we could use queues to plumb them together.

Setting up the environment
==========================

Dependencies
------------
Install the dependencies::

  pip install -r requirements.txt

If using a Python version before 2.6 then simplejson is needed::

  pip install simplejson

Setup
-----
Install the package::

  python setup.py install

Unit tests
==========
Run::

  python tests/testbasics.py

Or use nose to also test the module doc-blocks (you must install nose first).::

  pip install nose
  nosetests

In test-mode, modules needing user input use the default values rather than
prompting the user. This is done by setting `context.test==True`.

Usage
=====
There are two ways to translate a Yahoo pipe into Python.

1. Create a Python script pipeline which wraps the pipe in a function. This
function can then be imported and run from another Python program, i.e,
compiled.

2. Create the Python pipeline on-the-fly and execute it within the current
process, i.e., interpreted.

1. Compiling a Python script pipeline
------------------------------------------
You can create Python scripts by pulling directly from a Yahoo! Pipe::

  python pipe2py/compile.py -p pipe_id

or loading a json pipe file.::

  python pipe2py/compile.py tests/pipelines/pipe_name.json

If you load from a json pipe file, you should name the files pipe_PIPEID.json,
where `PIPEID` is the Yahoo ID for the pipeline, e.g.::

  pipe_188eca77fd28c96c559f71f5729d91ec.json

Both of these methods will create a python file named
after the input argument with a .py extension (using the
`compile.parse_pipe_def` and `compile.stringify_pipe` functions), e.g.::

  pipe2py/pypipelines/pipe_188eca77fd28c96c559f71f5729d91ec.py

Sub-pipes are expected to be contained in the `pipe2py/pypipelines` folder and
named pipe_PIPEID.py, where `PIPEID` is the Yahoo ID for the pipeline, e.g.::

  pipe_2de0e4517ed76082dcddf66f7b218057.py

Then compile.py will output files that can then be run directly, e.g.::

  python pipe2py/pypipelines/pipe_188eca77fd28c96c559f71f5729d91ec.py

or imported into other pipelines.::

  from tests.pypipelines.pipe_188eca77fd28c96c559f71f5729d91ec import pipe_188eca77fd28c96c559f71f5729d91ec
  from pipe2py import Context

  pipeline = pipe_188eca77fd28c96c559f71f5729d91ec(Context())
  print list(pipeline)

2. Interpreting a pipeline and executing in-process
---------------------------------------------------
First, start out with a context and pipe name, e.g.::

  from pipe2py import Context

  pipe_name = 'pipe_188eca77fd28c96c559f71f5729d91ec'

a) Then you can create pipelines from json pipe files.::

  from pipe2py.compile import parse_pipe_def, build_pipeline
  from os import path as p
  from json import loads

  pipe_file_name = p.join('tests', 'pipelines', '%s.json' % pipe_name)
  pjson = open(pipe_file_name).read()
  pipe_def = loads(pjson)
  pipe = parse_pipe_def(pipe_def, pipe_name)
  pipeline = build_pipeline(Context(), pipe)

b) or from an imported pipe module::

  from importlib import import_module

  module = import_module('tests.pypipelines.%s' % pipe_name)
  pipe_generator = getattr(module, pipe_name)
  pipeline = pipe_generator(Context())

either way, you can now output the content, e.g.::

  print list(pipeline)

Inputs
======

Some pipelines need to prompt the user for input values. When running a
compiled pipe, it defaults to prompting the user via the console, but in other
situations this may not be appropriate, e.g. when integrating with a website.
In such cases, the input values can instead be read from the pipe's context (a
set of values passed into every pipe). The context.inputs dictionary can be
pre-populated with user input before the pipe is executed.

To determine which prompts are needed, the pipeline can be called initially
with `context.describe_input==True`, and this will return a list of tuples
defining the inputs needed (it will not execute the pipe)::

  from pipe2py import Context
  from tests.pypipelines.pipe_1LNyRuNS3BGdkTKaAsqenA import pipe_1LNyRuNS3BGdkTKaAsqenA
  context = Context(describe_input=True)
  print pipe_1LNyRuNS3BGdkTKaAsqenA(context)

  >>> [(u'', u'textinput1', u'Stock Symbol:', u'text', u'yhoo'), (u'', u'textinput2', u'Search Term:', u'text', u'')]

Each tuple is of the form: `(position, name, prompt, type, default)`.

The list of tuples is sorted by position, i.e. the order in which they should
be presented to the user. The name should be used as a key in the
`context.inputs` dictionary. The prompt is the prompt for the user. Type is
the data type, e.g. text, number. And default is the default value (used if no
value is given), e.g. to run the above pipe with pre-defined inputs, and no
console prompting::

  from pipe2py import Context
  from tests.pypipelines.pipe_1LNyRuNS3BGdkTKaAsqenA import pipe_1LNyRuNS3BGdkTKaAsqenA
  context = Context(inputs={'textinput1': 'IBM'}, test=True)
  print list(pipe_1LNyRuNS3BGdkTKaAsqenA(context))
