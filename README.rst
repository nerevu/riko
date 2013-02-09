A project to compile Yahoo! Pipes into Python 
(see it hosted on Google App Engine: http://pipes-engine.appspot.com)

Design
======
The Yahoo pipelines are translated into pipelines of Python generators which 
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

Each Yahoo module is coded as a separate Python module. This might help in
future if the generators are made to run on separate processors/machines and 
we could use queues to plumb them together.


Setting up the environment
==========================
Install the package::

  python setup.py install


Dependencies
------------
If you need the 'XPath Fetch Page' module, lxml (http://lxml.de/) is 
required, e.g.::
  
  pip install lxml

If you use the html5 parser option for the 'XPath Fetch Page' module, 
html5lib (http://code.google.com/p/html5lib/) is also required, e.g.::
  
  pip install html5lib


If using a Python version before 2.6 then simplejson is needed:
  
  * http://pypi.python.org/pypi/simplejson

Unit tests
==========
Run in the test directory::

  python testbasics.py

In test-mode, modules needing user input use the default values rather than 
prompting the user. This is done by setting `context.test==True`.


Usage
=====
There are two ways to translate a Yahoo pipe into Python. One outputs a Python 
script which wraps the pipeline in a function which can then be imported and 
run from another Python program (i.e. compiled). The other interprets the 
pipeline on-the-fly and executes it within the current process 
(i.e. interpreted).

1. Compiling a pipeline to a Python script
------------------------------------------
Both of the following will create a python file named after the input argument 
with a .py extension (using the `compile.parse_and_write_pipe` function). This 
file can then be run directly or imported into other pipelines.

The first pulls the pipeline definition directly from Yahoo. The second loads 
the pipeline definition from a file:

  * python compile.py -p pipelineid
  
  or
  
  * python compile.py pipelinefile
  
Subpiplines are expected to be contained in python files named pipe_PIPEID.py,
where `PIPEID` is the Yahoo ID for the pipeline, e.g.

  pipe_2de0e4517ed76082dcddf66f7b218057.py

So if you do use the second option you should store your pipeline definitions 
in files named the same way, e.g.

  pipe_2de0e4517ed76082dcddf66f7b218057.json

then compile.py will output files with the expected naming convention.
  
2. Interpreting a pipeline and executing in-process
---------------------------------------------------
Example::

    from pipe2py.compile import parse_and_build_pipe
    from pipe2py import Context

    pipe_def = """json representation of the pipe"""

    p = parse_and_build_pipe(Context(), pipe_def)

    for i in p:
        print i


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
defining the inputs needed (it will not execute the pipe), e.g.::

    context = Context(describe_input=True)
    p = pipe_ac45e9eb9b0174a4e53f23c4c9903c3f(context, None)
    need_inputs = p
    print need_inputs

    >>> [(u'0', u'username', u'Twitter username', u'text', u''), 
    ...  (u'1', u'statustitle', 
    ...   u'Status title [string] or [logo] means twitter icon', u'text', 
    ...   u'logo')]

Each tuple is of the form::

  (position,
   name,
   prompt,
   type,
   default)

The list of tuples is sorted by position, i.e. the order in which they should 
be presented to the user. The name should be used as a key in the 
`context.inputs` dictionary. The prompt is the prompt for the user. Type is 
the data type, e.g. text, number. And default is the default value (used if no 
value is given), e.g. to run the above pipe with pre-defined inputs, and no
console prompting::

    context = Context(inputs={'username':'greg', 'statustitle':'logo'}, 
                      console=False)
    p = pipe_ac45e9eb9b0174a4e53f23c4c9903c3f(context, None)
    for i in p:
        print i

