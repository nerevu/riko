riko: composable stream processing for Python
=============================================

|ci| |pypi| |versions| |license|

.. contents::
   :local:
   :depth: 2

Introduction
------------

**riko** is a pure Python `library`_ for building data-processing ``streams``.
``riko`` combines reusable, configuration-driven `modules`_ with `synchronous`_,
`asynchronous`_, and `parallel execution`_ APIs. It is particularly useful for
processing RSS feeds, web content, text, and structured files.

``riko`` also supplies a `command-line interface`_ for executing ``flows``, i.e.,
stream processors aka ``pipelines``.

Requirements & Installation
---------------------------

``riko`` has been tested and is known to work on Python 3.12, 3.13, and 3.14.

Install the latest published release from PyPI:

.. code-block:: bash

    python -m pip install riko

``riko`` installs a slim core by default. View the `installation doc`_ for advanced
installation options.

Quick start
-----------

The following example fetches a webpage, splits its text into words, and counts the
number of times each word appears.

.. code-block:: python

    >>> from riko import get_path, Pipeline
    >>>
    >>> ### Set the module configurations ###
    >>> #
    >>> # Notes:
    >>> #   1. look up cached html file in the `data` directory
    >>> #   2. fetch text in the 'body' tag and strip html tags
    >>> #   3. replace newlines with spaces and assign the result to 'content'
    >>> #   4. split text in words using whitespace as the delimiter
    >>> #   5. count the number of times each word appears
    >>>
    >>> url = get_path('users.jyu.fi.html')                                # 1
    >>> fetch_conf = {
    ...     'url': url,
    ...     'start': '<body>',
    ...     'end': '</body>',
    ...     'detag': True,
    ... }
    >>> replace_rule = [
    ...     {'find': '\r\n', 'replace': ' '},
    ...     {'find': '\n', 'replace': ' '},
    ... ]
    >>> replace_conf = {'rule': replace_rule}
    >>>
    >>> pipeline = (
    ...     Pipeline.from_module('fetchpage', conf=fetch_conf)             # 2
    ...     .strreplace(conf=replace_conf, options={'assign': 'content'})  # 3
    ...     .tokenizer(conf={'delimiter': ' '}, options={'emit': True})    # 4
    ...     .count(conf={'count_key': 'content'})                          # 5
    ... )
    >>>
    >>> with pipeline.open() as stream:
    ...     next(stream)
    ...     next(stream)
    {'Tidy': 1}
    {'your': 1}

Motivation
----------

Why I built riko
^^^^^^^^^^^^^^^^

I wanted a small-footprint, pure-Python library for processing data streams. In
particular, I wanted to fetch RSS feeds and web pages and process records without
needing to deploy a scheduler, cluster, or message queue.

The basic idea is deliberately simple: dictionary-like records flow through configurable
modules. A pipeline is an immutable definition that can run synchronously (or
asynchronously via async/await), and spread work across threads or processes.

Why you should use riko
^^^^^^^^^^^^^^^^^^^^^^^

``riko`` is a good fit when you want a batteries included, reusable, data-processing
abstraction.

In particular, riko provides:

- a pure-Python, embedded execution model with no required external services
- a library of configuration-driven modules for filtering, sorting, parsing, transforming, aggregating, and composing streams
- first-class RSS/Atom and web-content processing
- synchronous and asynchronous APIs
- local thread and process-pool execution
- lazy iterator-oriented processing
- workflows written in Python or stored as JSON
- tools to inspect, execute, and compile pipelines

Why you shouldn't use riko
^^^^^^^^^^^^^^^^^^^^^^^^^^

``riko`` does not try to be a distributed stream-processing engine, durable workflow
scheduler, or dataframe query engine.

It is usually not the right tool when you need:

- execution across a cluster
- durable keyed state and recovery after worker failure
- persistent scheduling, retries, or task dependency management
- a workflow service/UI
- event-triggered infrastructure automation
- dataframe-scale columnar analytics or query optimization

``riko`` can instead run inside a worker or task managed by such systems.

Choosing riko
^^^^^^^^^^^^^

Several Python projects overlap with `riko`, but they optimize for different parts
of the data-processing problem.

+------------------------------------------+------------------------------------------------------------------+
| Project  | Distinctive strength          | Prefer it for...                                                 |
+==========+===============================+==================================================================+
| dlt_     | Declarative, schema-aware     | moving data from REST APIs into warehouses/lakes/databases       |
|          | ingestion                     |                                                                  |
+------------------------------------------+------------------------------------------------------------------+
| Singer_  | Standardized taps and targets | replicating data from various sources into many destinations     |
+------------------------------------------+------------------------------------------------------------------+
| Bytewax_ | Stateful streaming runtime    | keyed state, recovery, workers, or distributed stream processing |
+------------------------------------------+------------------------------------------------------------------+
| Bonobo_  | Injectable services and I/O   | traditional ETL graphs and runtime-injected infrastructure       |
+------------------------------------------+------------------------------------------------------------------+
| Streamz_ | Continuous stream graphs      | push-oriented streams, branching, backpressure, or live windows  |
+------------------------------------------+------------------------------------------------------------------+
| petl_    | Rich lazy table algebra       | joins, reshaping, and data-quality operations                    |
+------------------------------------------+------------------------------------------------------------------+
| ``riko`` | Config-driven pipelines       | broad library of reusable, JSON serializable modules             |
+------------------------------------------+------------------------------------------------------------------+

The closest comparison depends on what part of `riko` you care about.

dlt_ is a Python ingestion framework/library with similarities to ``riko`` in REST
ingestion, incremental extraction, schema-aware loading, and Python-native data
handling. dlt primarily allows you to "get data out a source reliably and into a
well-structured destination." It provides primitives for pagination, auth, and schema
normalization. This contrasts with riko's main use-case of processing and composing
streams of records.

`Singer`_ is a connector protocol that standardizes how sources (``taps``) and
destinations (``targets``) exchange records, schemas, and replication state. It
overlaps with ``riko`` at the extraction and data-movement boundaries. Singer is a
better fit when the primary goal is source-to-destination replication. ``riko`` instead
places more emphasis on transforming and composing records.

`Bytewax`_ is the natural direction when a workload grows beyond ``riko``'s intended
scope and requires durable keyed state, recovery, or distributed stream processing.

`petl`_ and `Bonobo`_, like ``riko``, are both lightweight ETL libraries. Compared to
``riko``, petl is more table-oriented and provides a deeper relational/data-wrangling
vocabulary. Bonobo centers execution around an ETL graph of transformation nodes.

`Streamz`_ overlaps most with ``riko``'s stream-composition and fan-out model, but
places more emphasis on continuous push-based streams, windowing, and reactive dataflow.

``riko`` provides more "batteries included" data-processing vocabulary. It exposes common
operations (filtering, truncating, searching, etc.) as configurable, reusable ``modules``
rather than requiring a Python callable. ``riko`` also provides first-class support for
web-content (RSS/Atom feeds, HTML/XML, and JSON) and a simple JSON format for storing
workflows.

Design Principles
-----------------

Overview
^^^^^^^^

Here's the ``riko`` vocabulary at a glance:

+---------------------+---------------------------------------+----------------------------------------------------+
| Term                | Meaning                               | Example                                            |
+=====================+=======================================+====================================================+
| ``item``            | one dictionary of fields              | ``{'title': 'Example'}``                           |
+---------------------+---------------------------------------+----------------------------------------------------+
| ``stream``          | an iterator of ``item``               | ``iter([{'title': 'Example'}])``                   |
+---------------------+---------------------------------------+----------------------------------------------------+
| ``items``           | an iterable of ``item``               | ``[{'title': 'Example'}]``                         |
+---------------------+---------------------------------------+----------------------------------------------------+
| ``module``          | a named, reusable stream operation    | ``join``, ``slugify``, ``uniq``                    |
+---------------------+---------------------------------------+----------------------------------------------------+
| ``operator``        | a module that consumes a ``stream``   | ``count``, ``filter``, ``reverse``                 |
+---------------------+---------------------------------------+----------------------------------------------------+
| ``processor``       | a module that consumes an ``item``    | ``urlparse``, ``fetch``, ``hash``                  |
+---------------------+---------------------------------------+----------------------------------------------------+
| ``splitter``        | a module yielding several ``streams`` | ``split``                                          |
+---------------------+---------------------------------------+----------------------------------------------------+
| ``node``            | a ``module`` with its configuration   | ``.truncate(conf={'count': 3})``                   |
+---------------------+---------------------------------------+----------------------------------------------------+
| ``pipeline``        | a chain of ``nodes``                  | ``Pipeline.from_module(...).count()``              |
+---------------------+---------------------------------------+----------------------------------------------------+
| ``seed``            | the data a ``pipeline`` starts from;  | ``pipeline(items)``, ``items | pipeline``          |
|                     | can be an ``item``, ``stream``, or    | ``pipeline.open(items)``                           |
|                     | ``items``                             |                                                    |
+---------------------+---------------------------------------+----------------------------------------------------+
| ``Context``         | input values + ``ExecutionMode``      | ``Context(inputs=...)``                            |
+---------------------+---------------------------------------+----------------------------------------------------+

Core concepts
^^^^^^^^^^^^^

The primary data structures in ``riko`` are the ``item`` and ``stream``. An ``item``
is just a Python dictionary, and a ``stream`` is an iterator of ``item``. You can
create a ``stream`` manually with something as simple as
``iter([{'content': 'hello world'}])``. You manipulate ``streams`` in
``riko`` via ``modules``. A ``module`` is a named, reusable operation that accepts
a ``seed`` (e.g., ``{'content': 'hello world'}``), and returns a ``stream``.

``riko`` ``modules`` come in three types: ``processor``, ``operator``, and ``splitter``.
An ``operator`` operates on a ``stream``, not on individual items. E.g., ``count``,
``filter``, and ``reverse``. Use ``Pipeline.from_module`` to create a ``pipeline`` from
any ``module``. Configure a module via ``conf``, e.g., ``from_module(name, conf=...)``.

``riko`` has a typed discovery tree (``Sources``/``Transforms``/``Sinks``) that holds the
names of all built-in modules. These enums let your editor autocomplete module names and
catch typos, so you don't need to memorize each module's name. Call the resulting
``pipeline`` with a ``seed`` to get a single-use ``stream`` you can iterate, or collect
with ``list()``. To read just one ``item``, use ``pipeline.first(seed)``, which also
closes the run.

.. code-block:: python

    >>> from riko import Pipeline, Transforms
    >>>
    >>> items = [{'title': 'riko pt. 1'}, {'title': 'riko pt. 2'}]
    >>> pipeline = Pipeline.from_module(Transforms.REVERSE)
    >>> list(pipeline(items))
    [{'title': 'riko pt. 2'}, {'title': 'riko pt. 1'}]

A ``processor`` processes an individual ``item``. E.g., ``fetchsitefeed``, ``hash``,
``itembuilder``, and ``regex``. Call options such as ``field``, ``assign``, and ``emit``
are passed as the ``options`` mapping. This example also showcases the ``.first()``
convenience method.

.. code-block:: python

    >>> from riko import Pipeline, Transforms
    >>>
    >>> item = {'title': 'riko pt. 1'}
    >>> pipeline = Pipeline.from_module(Transforms.HASH, options={'field': 'title'})
    >>> pipeline.first(item)['hash']
    1104819838

Some ``processors``, e.g., ``tokenizer``, return multiple results.

.. code-block:: python

    >>> from riko import Pipeline, Transforms
    >>>
    >>> items = [{'title': 'riko pt. 1'}]
    >>> pipeline = Pipeline.from_module(
    ...     Transforms.TOKENIZER, conf={'delimiter': ' '}, options={'field': 'title'}
    ... )
    >>> list(pipeline(items))
    [{'content': 'riko'}, {'content': 'pt.'}, {'content': '1'}]

``operators`` are split into sub-types: ``aggregator`` and ``composer``.
``aggregators``, e.g., ``sum`` and ``count``, combine all ``items`` of an input
``stream`` into an output ``stream`` containing a single ``item``.

.. code-block:: python

    >>> from riko import Pipeline, Transforms
    >>>
    >>> items = [{'title': 'riko pt 1', 'pages': 3}, {'title': 'riko pt 2', 'pages': 5}]
    >>> list(Pipeline.from_module(Transforms.SUM, conf={'sum_key': 'pages'})(items))
    [{'sum': Decimal('8')}]

Astute observers may have noticed from the "Word Count" example up top, that ``count``
can return multiple items if you pass in the ``count_key`` config option.

.. code-block:: python

    >>> from riko import Pipeline, Transforms
    >>>
    >>> items = [{'title': 'riko pt 1'}, {'title': 'riko pt 2'}]
    >>> pipeline = Pipeline.from_module(Transforms.COUNT, conf={'count_key': 'title'})
    >>> list(pipeline(items))
    [{'riko pt 1': 1}, {'riko pt 2': 1}]

``composers``, e.g., ``filter`` and ``sort``, select or reorder the ``items`` of an
input ``stream`` without changing them.

.. code-block:: python

    >>> from riko import Pipeline, Transforms
    >>>
    >>> items = [{'title': 'riko pt 1'}, {'title': 'riko pt 2'}]
    >>> rule = {'field': 'title', 'op': 'contains', 'value': '2'}
    >>> list(Pipeline.from_module(Transforms.FILTER, conf={'rule': rule})(items))
    [{'title': 'riko pt 2'}]

``processors`` are split into sub-types of ``source`` and ``transformer``. A ``source``,
e.g., ``itembuilder``, can create a ``stream`` without a ``seed``, while a
``transformer``, e.g. ``hash`` can only transform its input.

.. code-block:: python

    >>> from riko import Pipeline, Sources
    >>>
    >>> attrs = {'key': 'title', 'value': 'riko pt. 1'}
    >>> Pipeline.from_module(Sources.ITEMBUILDER, conf={'attrs': attrs}).first()
    {'title': 'riko pt. 1'}

The following table summarizes these observations:

+-----------+-----------------+-----------------------------+-----------------------------------+
| Type      | Sub-type        | Meaning                     | Example                           |
+===========+=================+=============================+===================================+
| processor | ``source``      | creates a ``stream``        | ``itembuilder``, ``fetch``        |
|           +-----------------+-----------------------------+-----------------------------------+
|           | ``transformer`` |  manipulates an ``item``    | ``hash``, ``rename``, ``regex``   |
+-----------+-----------------+-----------------------------+-----------------------------------+
| operator  | ``composer``    | selects/orders a ``stream`` | ``filter``, ``sort``, ``union``   |
|           +-----------------+-----------------------------+-----------------------------------+
|           | ``aggregator``  | summarizes a ``stream``     | ``count``, ``sum``                |
+-----------+-----------------+-----------------------------+-----------------------------------+
| splitter  | ``splitter``    | copies a ``stream``         | ``split``                         |
+-----------+-----------------+-----------------------------+-----------------------------------+

Note: Since some ``modules`` support more than one subtype depending on their options,
view the `FAQ`_ for steps on runtime discovery via `discovering modules`_.

If you are unsure of a ``module``'s module type, check its metadata.

.. code-block:: python

    >>> from riko import get_module_metadata, Sources, Transforms
    >>>
    >>> fetchpage = get_module_metadata(Sources.FETCHPAGE)
    >>> fetchpage.name, fetchpage.type, fetchpage.subtype
    ('fetchpage', 'processor', 'source')
    >>> count = get_module_metadata(Transforms.COUNT)
    >>> count.name, count.type, count.subtype
    ('count', 'operator', 'aggregator')

Note: ``type`` and ``subtype`` are mutually exclusive: a subtype implies its type.

``Pipeline`` performs this check for you to allow for convenient method chaining: any
module name is available as a method that appends a ``node`` for that ``module``. E.g.,
``.reverse()`` appends a ``reverse`` ``node``, takes its configuration as ``conf=...``,
and takes its call options as ``options=...``.

The chained ``pipeline`` is composable: the output stream of each ``node`` becomes the
input stream of the next.

.. code-block:: python

    >>> from riko import Pipeline, Sources
    >>>
    >>> attrs = {'key': 'content', 'value': "Let's talk about riko!"}
    >>> pipeline = Pipeline.from_module(Sources.ITEMBUILDER, conf={'attrs': attrs})
    >>> item = pipeline.hash().first()
    >>> item['content'], item['hash']
    ("Let's talk about riko!", 197222720)

To chain a ``module`` name held in a variable, a discovery enum such as
``Transforms.REVERSE``, or a dotted extension name such as ``example.shout``, use the
``.pipe(name)`` general form.

.. code-block:: python

    >>> from riko import Pipeline, Sources
    >>>
    >>> attrs = {'key': 'content', 'value': "Let's talk about riko!"}
    >>> pipeline = Pipeline.from_module(Sources.ITEMBUILDER, conf={'attrs': attrs})
    >>> module_name = 'hash'
    >>> item = pipeline.pipe(module_name).first()
    >>> item['content'], item['hash']
    ("Let's talk about riko!", 197222720)

The ``|`` operator chains the same way. A ``Pipeline`` on the left side feeds ``items``
to a module name or another ``Pipeline`` on the right side. A module name may be a plain
string or a discovery enum (e.g., ``Transforms``).

.. code-block:: python

    >>> from riko import Pipeline, Sources, Transforms
    >>>
    >>> attrs = {'key': 'content', 'value': "Let's talk about riko!"}
    >>> pipeline = Pipeline.from_module(Sources.ITEMBUILDER, conf={'attrs': attrs})
    >>> item = (pipeline | Transforms.HASH).first()
    >>> item['content'], item['hash']
    ("Let's talk about riko!", 197222720)

``items`` on the left of ``|`` seed a ``pipeline``.

.. code-block:: python

    >>> from riko import Pipeline, Transforms
    >>>
    >>> items = [{'title': 'riko pt. 1'}, {'title': 'riko pt. 2'}]
    >>> list(items | Pipeline.from_module(Transforms.REVERSE))
    [{'title': 'riko pt. 2'}, {'title': 'riko pt. 1'}]

View the `Cookbook`_ for advanced examples including how to wire in values from other
modules or accept user input.

Usage
-----

``riko`` can be used directly as a Python library.

Usage Index
^^^^^^^^^^^

- `Fetching data`_
- `Synchronous processing`_
- `Parallel processing`_
- `Asynchronous processing`_
- `Built-in modules`_
- `Pipeline lifecycle`_

Fetching data
^^^^^^^^^^^^^

``riko`` can fetch data such as HTML, JSON, CSV, etc. from both local and remote
filepaths via ``source`` ``modules``:

.. code-block:: python

    >>> from riko import get_path, Pipeline, Sources
    >>>
    >>> pipeline = Pipeline.from_module(Sources.FETCH, conf={'url': get_path('feed.xml')})
    >>> item = pipeline.first()
    >>> {'author', 'content', 'id', 'link', 'published', 'summary', 'title'} <= set(item)
    True
    >>> item['title'], item['author'], item['id']
    ('Donations', {'name': 'WriteToReply', 'uri': None}, 'http://writetoreply.org/?page_id=111')

View the `FAQ`_ for a complete list of supported `file types`_ and
`protocols`_; and `Fetching data and feeds`_ for more examples.

Synchronous processing
^^^^^^^^^^^^^^^^^^^^^^

``riko`` can modify a ``stream`` via ``transformer``,  ``composer``, and ``aggregator``
``modules``:

.. code-block:: python

    >>> from riko import get_path, Pipeline, Sources
    >>>
    >>> fetch_conf = {'url': get_path('feed.xml')}
    >>> filter_rule = {'field': 'title', 'op': 'contains', 'value': 'a'}
    >>>
    >>> # The following pipeline will:
    >>> #   1. fetch a (cached) RSS feed
    >>> #   2. filter for items with an 'a' in the title
    >>> #   3. sort the items ascending by title
    >>> #
    >>> # Note: sorting is not lazy so take caution when using this module
    >>>
    >>> pipeline = (
    ...     Pipeline.from_module(Sources.FETCH, conf=fetch_conf)   # 1
    ...     .filter(conf={'rule': filter_rule})                    # 2
    ...     .sort(conf={'rule': {'field': 'title'}})               # 3
    ... )
    >>>
    >>> pipeline.first()['title']
    'Donations'

View `modules`_ for a complete list of available ``modules``.

Parallel processing
^^^^^^^^^^^^^^^^^^^

By default, ``processors`` process one ``item`` at a time. You can declare
execution-wide concurrency on a ``Pipeline`` via ``with_execution``. This allows you
to select where per-item work runs (``executor``), cap how much work runs at once
(``concurrency``), and choose whether items keep their source order (``ordered``).
``operators`` such as ``sort`` and ``count`` are not impacted.

Like every other ``Pipeline`` method, it derives a new ``pipeline`` rather than mutating
the definition.

.. code-block:: python

    from riko import get_path, Pipeline, Sources

    fetch_conf = {'url': get_path('feed.xml')}
    filter_rule = {'field': 'title', 'op': 'contains', 'value': 'a'}

    # The following pipeline will:
    #   1. fetch a (cached) RSS feed
    #   2. filter for items with an 'a' in the title
    #   3. hash each title
    #   4. perform the hashing in parallel four items at a time
    #
    # Note: no point in sorting before the hash since unordered execution (the
    # default) doesn't guarantee order
    pipeline = (
        Pipeline.from_module(Sources.FETCH, conf=fetch_conf)    # 1
        .filter(conf={'rule': filter_rule})                     # 2
        .hash(options={'field': 'title'})                       # 3
        .with_execution(concurrency=4)                          # 4
    )

    sorted(item['title'] for item in pipeline)[:3]

Asynchronous processing
^^^^^^^^^^^^^^^^^^^^^^^

To enable asynchronous processing, you must install the ``async`` extra.

.. code-block:: bash

    python -m pip install "riko[async]"

The same ``pipeline`` then runs asynchronously under ``async for``. If you want to exit
early, use ``pipeline.open()`` to create a context manager (iterate it via
``async with``). Leaving the ``with`` block closes the run, but a bare ``break`` out of
``async for`` releases the run only once the iterator is garbage collected.

.. code-block:: python

    >>> from riko import get_path, Pipeline, run, Sources
    >>>
    >>> fetch_conf = {'url': get_path('feed.xml')}
    >>> filter_rule = {'field': 'title', 'op': 'contains', 'value': 'a'}
    >>>
    >>> # The following pipeline will:
    >>> #   1. fetch a (cached) RSS feed
    >>> #   2. filter for items with an 'a' in the title
    >>>
    >>> async def main():
    ...     pipeline = (
    ...         Pipeline.from_module(Sources.FETCH, conf=fetch_conf)   # 1
    ...         .filter(conf={'rule': filter_rule})                    # 2
    ...     )
    ...
    ...     async with pipeline.open() as stream:
    ...         first = await anext(stream)
    ...         print(first['title'])
    >>>
    >>> run(main)
    Donations

Built-in modules
^^^^^^^^^^^^^^^^

``riko`` ships `52 built-in`_ ``modules``. The table below summarizes them.

+-----------------------------+----------------------------------------------------------+--------------------------------------------------+
| Group                       | Representative modules                                   | Purpose                                          |
+=============================+==========================================================+==================================================+
| Sources & readers           | ``itembuilder``, ``fetch``, ``fetchtable``, ``csv``      | build items from config, feeds, files, or input  |
+-----------------------------+----------------------------------------------------------+--------------------------------------------------+
| Selection & ordering        | ``filter``, ``sort``, ``truncate``, ``uniq``             | select, order, dedupe, or bound a stream         |
+-----------------------------+----------------------------------------------------------+--------------------------------------------------+
| Text & field transforms     | ``regex``, ``rename``, ``strreplace``, ``tokenizer``     | extract and transform string / item fields       |
+-----------------------------+----------------------------------------------------------+--------------------------------------------------+
| Type & numeric transforms   | ``typecast``, ``simplemath``, ``dateformat``, ``hash``   | convert types and derive fields                  |
+-----------------------------+----------------------------------------------------------+--------------------------------------------------+
| Aggregation & combination   | ``count``, ``sum``, ``join``, ``union``, ``split``       | summarize, merge, join, or copy streams          |
+-----------------------------+----------------------------------------------------------+--------------------------------------------------+
| Control & extension         | ``loop``, ``udf``, ``send``, ``receive``                 | run submodules, call funcs, fan out items        |
+-----------------------------+----------------------------------------------------------+--------------------------------------------------+
| RSS & location helpers      | ``fetchsitefeed``, ``exchangerate``, ``geolocate``       | feed and network-backed transformations          |
+-----------------------------+----------------------------------------------------------+--------------------------------------------------+
| Sinks & writers             | ``write``                                                | serialize a stream to a file (materializes it)   |
+-----------------------------+----------------------------------------------------------+--------------------------------------------------+

Pipeline lifecycle
^^^^^^^^^^^^^^^^^^

A ``Pipeline`` is an immutable *definition*, not a ``stream``. Every call starts a fresh
one-shot run. Running a ``pipeline`` twice iterates the seed twice. The run owns its
resources. Exhausting it or leaving its ``with pipeline.open(...)`` block early tears
the run down.

.. code-block:: python

    >>> from riko import export, Pipeline
    >>>
    >>> items = [{'content': 'a'}, {'content': 'b'}]
    >>> pipeline = Pipeline.from_module('hash')
    >>> len(list(pipeline(items)))
    2
    >>> len(list(pipeline(items)))
    2
    >>> with pipeline.open(items) as stream:
    ...     next(stream)
    {'content': 'a', 'hash': 1267964084}
    >>> export(pipeline(items), 'csv').getvalue()
    'content,hash\r\na,1267964084\r\nb,2297772648\r\n'

``export`` serializes a ``pipeline`` (or any ``stream``) to one of the ``Formats``;
see `exporting a stream`_ in the `Cookbook`_.

Command-line Interface
----------------------

``riko`` provides a command, ``run-pipe``, to execute pipe scripts, workflow modules
(``WorkflowModule``\s), and workflow documents (``WorkflowDocument``\s, i.e., serialized
``Workflow``\s). A pipe script is a Python file containing a function named ``pipe``
that returns a ``pipeline``. ``run-pipe`` prints each item of the resulting ``stream``.
E.g., ``pipe.py``

.. code-block:: python

    from riko import Pipeline, Sources

    conf1 = {'attrs': [{'value': 'https://google.com', 'key': 'content'}]}
    conf2 = {'rule': [{'find': 'com', 'replace': 'co.uk'}]}

    def pipe(test=False):
        itembuilder = Pipeline.from_module(Sources.ITEMBUILDER, conf=conf1)
        return itembuilder.strreplace(conf=conf2)

CLI Usage

  usage: run-pipe [pipeid] [-p PATH]

  description: Runs a pipe script, workflow module, or workflow document

  positional arguments:
    pipeid            The id of an example pipe script or workflow document.

  options:
    -h, --help            show this help message and exit
    -p PATH, --path PATH  Path to a pipe script, workflow module, or workflow document to
                          run, e.g. pipe.py or flow.json.
    -a, --async           Load async pipe.
    -t, --test            Run in test mode (uses default inputs).

Now to execute ``pipe.py``, type the command ``run-pipe --path pipe.py``. You should
then see the following output in your terminal:

.. code-block:: bash

    {'content': 'https://google.com', 'strreplace': 'https://google.co.uk'}

``run-pipe`` will also search the ``examples`` directory for pipe scripts. Type
``run-pipe demo`` and you should see the following output:

.. code-block:: bash

    Deadline to clear up health law eligibility near
    682

The ``examples`` directory bundles more runnable pipe scripts. E.g., try ``run-pipe
usage``, ``run-pipe simple1``, or ``run-pipe wired``. The `Cookbook`_ covers the
``register_alias``/``register_module`` runtime-registration examples.

``examples/workflows/*.json`` are ``WorkflowDocument``\s. ``run-pipe`` can run one
using either its path (``run-pipe -p flow.json``) or id (``run-pipe pipe_timezone``).
See the `DAG format`_ for details on the JSON structure.

Contributing
------------

Please mimic the coding style/conventions used in this repo. If you add new classes or
functions, please add the appropriate docstrings with examples. Also, make sure the
linter and tests pass.

View `Contributing doc`_ for more details.

Credits
-------

``riko`` started out as a fork of `pipe2py`_ which translated a Yahoo! Pipe [#] into
python code. ``riko`` has since diverged so much from ``pipe2py`` that little of the
original code-base remains.

Notes

.. [#] Discontinued in 2015, Yahoo! Pipes was a user friendly web application used to aggregate, manipulate, and mashup content from around the web. You can view what `remains`_

More Info
---------

- `FAQ`_ — the complete built-in ``module`` catalog and the export formats
- `Cookbook`_ — progressively organized, runnable recipes
- `DAG format`_ — the bare-bones DAG and workflow document formats,
  and the commands that convert, compile, and run them
- `Migration guide`_ — upgrading from the older versions or the ``legacy`` branch
- `Changelog`_ — release notes
- `Contributing doc`_ — contribution and issue-reporting guidance
- `issue tracker`_ — bugs, feature proposals, and questions

Project Structure
-----------------

.. code-block:: bash

    ┌── _docs/*               (internal documentation)
    ├── docs
    │   ├── AUTHORS.rst
    │   ├── CHANGES.rst
    │   ├── COOKBOOK.rst
    │   ├── DAG_FORMAT.rst
    │   ├── FAQ.rst
    │   ├── INSTALLATION.rst
    │   └── MIGRATION.rst
    ├── examples
    │   ├── *.py              (runnable pipe scripts)
    │   ├── workflows/*       (example WorkflowDocuments)
    │   ├── pyworkflows/*     (hand-written Python equivalents)
    │   └── riko-example-ext/ (example extension package)
    ├── riko
    │   ├── __init__.py       (stable public API)
    │   ├── base/             (constants, paths, logging, helpers, exceptions)
    │   ├── types/            (supported typing surface)
    │   ├── coercion/         (casts, generated config objects)
    │   ├── bado/             (async backend and iterator helpers)
    │   ├── definitions/      (immutable module, Context, resource, write, and workflow contracts)
    │   ├── io/               (sync/async URL and file I/O, serialization)
    │   ├── parsing/          (config, XML/HTML, and document parsing)
    │   ├── rss/              (feed discovery and parsing)
    │   ├── execution/        (sync/async executions, resource acquisition and cleanup)
    │   ├── runtime/          (export, compiler, registries, pipelines, pub/sub)
    │   ├── modules/          (the built-in modules)
    │   ├── ext/              (extension API: decorators, protocols)
    │   ├── cli/              (manage, run-pipe, benchmark, compile-workflow, build-workflow)
    │   └── data/*
    ├── tests
    │   ├── __init__.py
    │   ├── dags/*           (serialized PipeDag fixtures)
    │   ├── functional/*
    │   ├── internal/*
    │   ├── public/*
    │   ├── pyworkflows/*    (hand-written Python equivalents)
    │   └── workflows/*      (WorkflowDocument fixtures)
    ├── CLAUDE.md
    ├── conftest.py
    ├── CONTRIBUTING.rst
    ├── LICENSE
    ├── pyproject.toml
    ├── README.rst
    └── uv.lock

License
-------

``riko`` is distributed under the `MIT License`_.

.. _synchronous: #synchronous-processing
.. _asynchronous: #asynchronous-processing
.. _parallel execution: #parallel-processing
.. _parallel processing: #parallel-processing
.. _library: #usage

.. _Contributing doc: CONTRIBUTING.rst
.. _FAQ: docs/FAQ.rst
.. _modules: docs/FAQ.rst#what-modules-are-available
.. _discovering modules: docs/FAQ.rst#how-do-i-discover-installed-modules
.. _52 built-in: docs/FAQ.rst#what-modules-are-available
.. _file types: docs/FAQ.rst#what-file-types-are-supported
.. _protocols: docs/FAQ.rst#what-protocols-are-supported
.. _installation doc: docs/INSTALLATION.rst
.. _Migration guide: docs/MIGRATION.rst
.. _Changelog: docs/CHANGES.rst
.. _Cookbook: docs/COOKBOOK.rst
.. _DAG format: docs/DAG_FORMAT.rst
.. _issue tracker: https://github.com/nerevu/riko/issues
.. _Fetching data and feeds: docs/COOKBOOK.rst#fetching-data-and-feeds
.. _exporting a stream: docs/COOKBOOK.rst#exporting-a-stream

.. _pipe2py: https://github.com/ggaughan/pipe2py/
.. _Bonobo: https://www.bonobo-project.org
.. _petl: https://petl.readthedocs.io
.. _Singer: https://www.singer.io
.. _Streamz: https://streamz.readthedocs.io
.. _Bytewax: https://docs.bytewax.io
.. _dlt: https://dlthub.com/docs/intro
.. _remains: https://web.archive.org/web/20150930021241/http://pipes.yahoo.com/pipes/
.. _MIT License: http://opensource.org/licenses/MIT
.. _Apache Beam: https://beam.apache.org/documentation/programming-guide/
.. _RxPY: https://rxpy.readthedocs.io/en/latest/

.. |ci| image:: https://github.com/nerevu/riko/actions/workflows/ci.yml/badge.svg
    :target: https://github.com/nerevu/riko/actions/workflows/ci.yml
    :alt: CI status

.. |pypi| image:: https://img.shields.io/pypi/v/riko.svg
    :target: https://pypi.org/project/riko/
    :alt: Latest PyPI release

.. |versions| image:: https://img.shields.io/pypi/pyversions/riko.svg
    :target: https://pypi.org/project/riko/
    :alt: Supported Python versions

.. |license| image:: https://img.shields.io/pypi/l/riko.svg
    :target: https://opensource.org/licenses/MIT
    :alt: MIT license
