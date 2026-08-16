riko: composable stream processing for Python
=============================================

|ci| |pypi| |versions| |license|

.. contents::
   :local:
   :depth: 2

Introduction
------------

**riko** is a pure Python `library`_ for building data-processing ``streams``.
``riko`` combines reusable, configuration-driven modular `pipes`_ with `synchronous`_,
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

    >>> from riko import get_path, Sources, SyncPipe
    >>>
    >>> ### Set the pipe configurations ###
    >>> #
    >>> # Notes:
    >>> #   1. look up cached html file in the `data` directory
    >>> #   2. fetch text in the 'body' tag and strip html tags
    >>> #   3. replace newlines with spaces and assign the result to 'content'
    >>> #   4. split text in words using whitespace as the delimiter
    >>> #   5. count the number of times each word appears
    >>>
    >>> url = get_path('users.jyu.fi.html')                   # 1
    >>> fetch_conf = {'url': url, 'start': '<body>', 'end': '</body>', 'detag': True}
    >>> replace_conf = {
    ...     'rule': [{'find': '\r\n', 'replace': ' '}, {'find': '\n', 'replace': ' '}]
    ... }
    >>>
    >>> flow = (
    ...     SyncPipe(Sources.FETCHPAGE, conf=fetch_conf)      # 2
    ...     .strreplace(conf=replace_conf, assign='content')  # 3
    ...     .tokenizer(conf={'delimiter': ' '}, emit=True)    # 4
    ...     .count(conf={'count_key': 'content'})             # 5
    ... )
    >>>
    >>> next(flow)
    {'Tidy': 1}
    >>> next(flow)
    {'your': 1}

Motivation
----------

Why I built riko
^^^^^^^^^^^^^^^^

I wanted a small-footprint, pure-Python library for processing data streams. In
particular, I wanted to fetch RSS feeds and web pages and process records without
needing to deploy a scheduler, cluster, or message queue.

The basic idea is deliberately simple: dictionary-like records flow through configurable
pipes. Pipelines can run synchronously, asynchronous via async/await, or
parallelized across threads or processes.

Why you should use riko
^^^^^^^^^^^^^^^^^^^^^^^

``riko`` is a good fit when you want a batteries included, reusable, data-processing
abstraction.

In particular, riko provides:

- a pure-Python, embedded execution model with no required external services
- a library of configuration-driven pipes for filtering, sorting, parsing, transforming, aggregating, and composing streams
- first-class RSS/Atom and web-content processing
- synchronous and asynchronous APIs
- local thread and process-pool execution
- lazy iterator-oriented processing
- simple Python or JSON pipeline configuration and definition
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
| ``riko`` | Config-driven pipelines       | broad library of reusable, JSON serializable pipes               |
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
operations (filtering, truncating, searching, etc.) as configurable, reusable ``pipes``
rather than requiring a Python callable. ``riko`` also provides first-class support for
web-content (RSS/Atom feeds, HTML/XML, and JSON) and a simple JSON-based pipeline
definition format.

Design Principles
-----------------

Overview
^^^^^^^^

Here's the ``riko`` vocabulary at a glance:

+---------------------+---------------------------------------+--------------------------------------------------+
| Term                | Meaning                               | Example                                          |
+=====================+=======================================+==================================================+
| ``item``            | one dictionary-like record            | ``{'title': 'Example'}``                         |
+---------------------+---------------------------------------+--------------------------------------------------+
| ``stream``          | an iterator of ``item``               | ``iter([{'title': 'Example'}])`` or ``SyncPipe`` |
+---------------------+---------------------------------------+--------------------------------------------------+
| ``pipe``            | a configured stream operation         | ``join``, ``slugify``, ``uniq``                  |
+---------------------+---------------------------------------+--------------------------------------------------+
| ``operator``        | a pipe that consumes a ``stream``     | ``count``, ``filter``, ``reverse``               |
+---------------------+---------------------------------------+--------------------------------------------------+
| ``processor``       | a pipe that consumes an ``item``      | ``urlparse``, ``fetch``, ``hash``                |
+---------------------+---------------------------------------+--------------------------------------------------+
| ``splitter``        | a pipe returning multiple ``streams`` | ``split``                                        |
+---------------------+---------------------------------------+--------------------------------------------------+
| ``flow`` / pipeline | a chain of configured ``pipes``       | ``SyncPipe(...).count()``                        |
+---------------------+---------------------------------------+--------------------------------------------------+
| ``Context``         | runtime inputs + ``ExecutionMode``    | ``Context(inputs=...)``                          |
+---------------------+---------------------------------------+--------------------------------------------------+

Core concepts
^^^^^^^^^^^^^

The primary data structures in ``riko`` are the ``item`` and ``stream``. An ``item``
is just a Python dictionary, and a ``stream`` is an iterator of ``item``. You can
create a ``stream`` manually with something as simple as
``iter([{'content': 'hello world'}])``. You manipulate ``streams`` in
``riko`` via ``pipes``. A ``pipe`` is simply a function that accepts either a
``stream`` or ``item``, and returns a ``stream``.


Through ``SyncPipe`` and ``AsyncPipe`` classes, ``pipes`` are composable: the output of
each ``pipe`` is the input to the next ``pipe``.


``riko`` ``pipes`` come in three types: ``processor``, ``operator``, and ``splitter``.
An ``operator`` operates on a ``stream`` and is unable to handle individual items.
E.g., ``count``, ``filter``, and ``reverse``.

.. code-block:: python

    >>> from riko import SyncPipe, Transforms
    >>>
    >>> items = [{'title': 'riko pt. 1'}, {'title': 'riko pt. 2'}]
    >>> stream = SyncPipe(Transforms.REVERSE, items)
    >>> next(stream)
    {'title': 'riko pt. 2'}

A ``processor`` processes an individual ``item`` and can be parallelized across
threads or processes. E.g., ``fetchsitefeed``, ``hash``, ``itembuilder``, and ``regex``.

.. code-block:: python

    >>> from riko import SyncPipe, Transforms
    >>>
    >>> items = [{'title': 'riko pt. 1'}]
    >>> stream = SyncPipe(Transforms.HASH, items, field='title')
    >>> next(stream)['hash']
    1104819838

Some ``processors``, e.g., ``tokenizer``, return multiple results.

.. code-block:: python

    >>> from riko import SyncPipe, Transforms
    >>>
    >>> items = [{'title': 'riko pt. 1'}]
    >>> stream = SyncPipe(Transforms.TOKENIZER, items, conf={'delimiter': ' '}, field='title')
    >>> list(stream)
    [{'content': 'riko'}, {'content': 'pt.'}, {'content': '1'}]

``operators`` are split into sub-types: ``aggregator``
and ``composer``. ``aggregators``, e.g., ``count``, combine
all ``items`` of an input ``stream`` into a new ``stream`` with a single ``item``;
while ``composers``, e.g., ``filter``, create a new ``stream`` containing
some or all ``items`` of an input ``stream``.

.. code-block:: python

    >>> from riko import SyncPipe, Transforms
    >>>
    >>> items = [{'title': 'riko pt 1'}, {'title': 'riko pt 2'}]
    >>> list(SyncPipe(Transforms.COUNT, items))
    [{'count': 2}]

Astute observers may have noticed from the "Word Count" example up top, that ``count``
can return multiple items if you pass in the ``count_key`` config option.

.. code-block:: python

    >>> from riko import SyncPipe, Transforms
    >>>
    >>> stream = SyncPipe(Transforms.COUNT, items, conf={'count_key': 'title'})
    >>> list(stream)
    [{'riko pt 1': 1}, {'riko pt 2': 1}]

``processors`` are parallelizable and split into sub-types of ``source`` and
``transformer``. A ``source``, e.g., ``itembuilder``, can create a ``stream``, while
a ``transformer``, e.g. ``hash`` can only transform a source ``item``.

.. code-block:: python

    >>> from riko import Sources, SyncPipe
    >>>
    >>> attrs = {'key': 'title', 'value': 'riko pt. 1'}
    >>> next(SyncPipe(Sources.ITEMBUILDER, conf={'attrs': attrs}))
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

Note: Since some ``pipes`` support more than one subtype depending on their options,
view the `FAQ`_ for steps on runtime discovery via `discovering modules`_.

If you are unsure of the type of ``pipe`` you have, check its metadata.

.. code-block:: python

    >>> from riko import get_module_metadata, Sources, Transforms
    >>>
    >>> metadata = get_module_metadata(Sources.FETCHPAGE)
    >>> metadata.name, metadata.type, metadata.subtype
    ('fetchpage', 'processor', 'source')
    >>> metadata = get_module_metadata(Transforms.COUNT)
    >>> metadata.name, metadata.type, metadata.subtype
    ('count', 'operator', 'aggregator')

Note: ``type`` and ``subtype`` are mutually exclusive: a subtype implies its type.

``SyncPipe``/``AsyncPipe`` perform this check for you to allow for convenient method
chaining and transparent parallelization.

.. code-block:: python

    >>> from riko import Sources, SyncPipe
    >>>
    >>> attrs = [
    ...     {'key': 'title', 'value': 'riko pt. 1'},
    ...     {'key': 'content', 'value': "Let's talk about riko!"}
    ... ]
    >>> flow = SyncPipe(Sources.ITEMBUILDER, conf={'attrs': attrs}).hash()
    >>> item = next(flow)
    >>> item['title'], item['content'], item['hash']
    ('riko pt. 1', "Let's talk about riko!", 197222720)

The ``|`` operator chains the same way. It takes a module name or a ``(name, conf)``
tuple. The later is handy when the next ``pipe``'s name is computed. A name may be a
plain string or a member of the typed discovery tree (``Sources``/``Transforms``/
``Sinks``).

.. code-block:: python

    >>> from riko import Sources, SyncPipe, Transforms
    >>>
    >>> attrs = [
    ...     {'key': 'title', 'value': 'riko pt. 1'},
    ...     {'key': 'content', 'value': "Let's talk about riko!"}
    ... ]
    >>> conf = {'attrs': attrs}
    >>> item = next(SyncPipe(Sources.ITEMBUILDER, conf=conf) | Transforms.HASH)
    >>> item['title'], item['hash']
    ('riko pt. 1', 197222720)

View the `Cookbook`_ for advanced examples including how to wire in
values from other pipes or accept user input.

Usage
-----

``riko`` can be used directly as a Python library.

Usage Index
^^^^^^^^^^^

- `Fetching data`_
- `Synchronous processing`_
- `Parallel processing`_
- `Asynchronous processing`_
- `Built-in pipes`_
- `Pipeline lifecycle`_

Fetching data
^^^^^^^^^^^^^

``riko`` can fetch data such as HTML, JSON, CSV, etc. from both local and remote
filepaths via ``source`` ``pipes``:

.. code-block:: python

    >>> from riko import get_path, Sources, SyncPipe
    >>>
    >>> stream = SyncPipe(Sources.FETCH, conf={'url': get_path('feed.xml')})
    >>> item = next(stream)
    >>> {'author', 'content', 'id', 'link', 'published', 'summary', 'title'} <= set(item)
    True
    >>> item['title'], item['author'], item['id']
    ('Donations', {'name': 'WriteToReply', 'uri': None}, 'http://writetoreply.org/?page_id=111')

View the `FAQ`_ for a complete list of supported `file types`_ and
`protocols`_; and `Fetching data and feeds`_ for more examples.

Synchronous processing
^^^^^^^^^^^^^^^^^^^^^^

``riko`` can modify a ``stream`` via ``transformer``,  ``composer``, and ``aggregator``
``pipes``:

.. code-block:: python

    >>> from riko import get_path, Sources, SyncPipe
    >>>
    >>> fetch_conf = {'url': get_path('feed.xml')}
    >>> filter_rule = {'field': 'title', 'op': 'contains', 'value': 'a'}
    >>>
    >>> # The following flow will:
    >>> #   1. fetch a (cached) RSS feed
    >>> #   2. filter for items with an 'a' in the title
    >>> #   3. sort the items ascending by title
    >>> #
    >>> # Note: sorting is not lazy so take caution when using this pipe
    >>>
    >>> flow = (
    ...     SyncPipe(Sources.FETCH, conf=fetch_conf)   # 1
    ...     .filter(conf={'rule': filter_rule})        # 2
    ...     .sort(conf={'rule': {'field': 'title'}})   # 3
    ... )
    >>>
    >>> next(flow)['title']
    'Donations'

View `pipes`_ for a complete list of available ``pipes``.

Parallel processing
^^^^^^^^^^^^^^^^^^^

An example using ``riko``'s parallel API to spawn a ``ThreadPool`` [#]_

.. code-block:: python

    >>> from riko import get_path, Sources, SyncPipe
    >>>
    >>> fetch_conf = {'url': get_path('feed.xml')}
    >>> filter_rule = {'field': 'title', 'op': 'contains', 'value': 'a'}
    >>>
    >>> # The following flow will:
    >>> #   1. fetch a (cached) RSS feed
    >>> #   2. filter for items with an 'a' in the title, in parallel (4 workers)
    >>> #
    >>> # Note: no point in sorting after the filter since parallel fetching doesn't
    >>> # guarantee order
    >>> flow = (
    ...     SyncPipe(Sources.FETCH, conf=fetch_conf, parallel=True, workers=4)  # 1
    ...     .filter(conf={'rule': filter_rule})                           # 2
    ... )
    >>>
    >>> sorted(item['title'] for item in flow)[:3]
    ['Donations', 'FAQ', 'General Comments']

Notes

.. [#] You can instead enable a ``ProcessPool`` by additionally passing ``threads=False`` to ``SyncPipe``, i.e., ``SyncPipe(Sources.FETCH, conf={'url': url}, parallel=True, threads=False)``.

Asynchronous processing
^^^^^^^^^^^^^^^^^^^^^^^

To enable asynchronous processing, you must install the ``async`` extra.

.. code-block:: bash

    python -m pip install "riko[async]"

.. code-block:: python

    >>> from riko import AsyncPipe, get_path, issync, run, Sources
    >>>
    >>> fetch_conf = {'url': get_path('feed.xml')}
    >>> filter_rule = {'field': 'title', 'op': 'contains', 'value': 'a'}
    >>>
    >>> # The following flow will:
    >>> #   1. fetch a (cached) RSS feed
    >>> #   2. filter for items with an 'a' in the title
    >>>
    >>> async def main():
    ...     stream = await (
    ...         AsyncPipe(Sources.FETCH, conf=fetch_conf)           # 1
    ...             .filter(conf={'rule': filter_rule}))            # 2
    ...
    ...     print(next(stream)['title'])
    >>>
    >>> print('Donations') if issync else run(main)
    Donations

Built-in pipes
^^^^^^^^^^^^^^

``riko`` ships `52 built-in`_ ``pipes``. The table below summarizes them.

+-----------------------------+----------------------------------------------------------+--------------------------------------------------+
| Group                       | Representative pipes                                     | Purpose                                          |
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
| Feed & location helpers     | ``fetchsitefeed``, ``exchangerate``, ``geolocate``       | feeds and network-backed transformations         |
+-----------------------------+----------------------------------------------------------+--------------------------------------------------+
| Sinks & writers             | ``write``                                                | serialize a stream to a file in-pipeline         |
+-----------------------------+----------------------------------------------------------+--------------------------------------------------+

Pipeline lifecycle
^^^^^^^^^^^^^^^^^^

``SyncPipe``/``AsyncPipe`` represent a *single* execution: iterating one
consumes the ``stream``, and iterating it again yields an empty ``stream``. Read the
``state``/``exhausted``/``closed``/``failed`` properties to inspect a pipe. Use it as a
context manager (or call ``close()``/``terminate()``) to release a parallel pipe's
worker pool deterministically.

.. code-block:: python

    >>> from riko import SyncPipe, Transforms
    >>>
    >>> flow = SyncPipe(Transforms.HASH, source=[{'content': 'a'}, {'content': 'b'}])
    >>> flow.state
    <PipeState.NEW: 'new'>
    >>> len(list(flow))
    2
    >>> flow.state
    <PipeState.EXHAUSTED: 'exhausted'>
    >>> flow.exhausted
    True

See the `Cookbook`_ for pool cleanup and the full state model.

Command-line Interface
----------------------

``riko`` provides a command, ``run-pipe``, to execute ``pipelines``. A
``pipeline`` is simply a file containing a function named ``pipe`` that creates
a ``flow`` and processes the resulting ``stream``. E.g., ``flow.py``

.. code-block:: python

    from riko import Sources, SyncPipe

    conf1 = {'attrs': [{'value': 'https://google.com', 'key': 'content'}]}
    conf2 = {'rule': [{'find': 'com', 'replace': 'co.uk'}]}

    def pipe(test=False):
        kwargs = {'conf': conf1, 'test': test}
        flow = SyncPipe(Sources.ITEMBUILDER, **kwargs).strreplace(conf=conf2)
        for i in flow:
            print(i)

CLI Usage

  usage: run-pipe [pipeid] [-p PATH]

  description: Runs a riko pipe

  positional arguments:
    pipeid            The pipeline to run from the examples directory.

  optional arguments:
    -h, --help        show this help message and exit
    -p, --path PATH   Path to a pipe file to run, e.g. flow.py.
    -a, --async       Load async pipe.
    -t, --test        Run in test mode (uses default inputs).

Now to execute ``flow.py``, type the command ``run-pipe --path flow.py``. You should
then see the following output in your terminal:

.. code-block:: bash

    {'content': 'https://google.com', 'strreplace': 'https://google.co.uk'}

``run-pipe`` will also search the ``examples`` directory for ``pipelines``. Type
``run-pipe demo`` and you should see the following output:

.. code-block:: bash

    Deadline to clear up health law eligibility near
    682

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

- `FAQ`_ — the complete built-in ``pipe`` and file-format catalog
- `Cookbook`_ — progressively organized, runnable recipes
- `DAG format`_ — compact and full JSON ``pipeline`` formats
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
    │   ├── MIGRATION.rst
    │   └── ROADMAP.md
    ├── examples/*
    ├── riko
    │   ├── __init__.py       (stable public API)
    │   ├── api.py            (stable API re-export hub)
    │   ├── autorss.py, cast.py, currencies.py, dates.py, locations.py, pprint2.py, topsort.py
    │   ├── collections.py    (SyncPipe, AsyncPipe, SyncCollection, AsyncCollection)
    │   ├── compile.py        (JSON pipe → executable pipeline / Python module)
    │   ├── context.py        (Context, ExecutionMode)
    │   ├── dotdict.py
    │   ├── paths.py          (get_path / get_abspath)
    │   ├── parsers.py        (sync XML/HTML parsing)
    │   │
    │   ├── _*.py             (private helpers: _feed, _io, _iterutils, _objectify,
    │   │                      _serialize, _strutils, _logging)
    │   ├── _pubsub/          (sync + async pub/sub hubs backing send/receive)
    │   ├── bado/             (async backend: __init__, io, itertools, mock, _util)
    │   ├── cli/              (manage, run-pipe, benchmark, compile, convert-dag, gen-config)
    │   ├── data/*
    │   ├── ext/              (extension API: decorators, protocols)
    │   ├── modules/*         (the built-in pipes)
    │   ├── templates/*       (codegen Jinja templates)
    │   └── types/            (compile, general, modules, values, configs, guards)
    ├── tests
    │   ├── __init__.py
    │   ├── conftest.py
    │   ├── dags/*           (bare-bones DAG fixtures)
    │   ├── functional/*
    │   ├── internal/*
    │   ├── pipelines/*      (JSON pipe definitions)
    │   ├── public/*
    │   └── pypipelines/*    (expected generated Python modules)
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
.. _pipes: docs/FAQ.rst#what-pipes-are-available
.. _discovering modules: docs/FAQ.rst#how-do-i-discover-installed-modules
.. _52 built-in: docs/FAQ.rst#what-pipes-are-available
.. _file types: docs/FAQ.rst#what-file-types-are-supported
.. _protocols: docs/FAQ.rst#what-protocols-are-supported
.. _installation doc: docs/INSTALLATION.rst
.. _Migration guide: docs/MIGRATION.rst
.. _Changelog: docs/CHANGES.rst
.. _Cookbook: docs/COOKBOOK.rst
.. _DAG format: docs/DAG_FORMAT.rst
.. _issue tracker: https://github.com/nerevu/riko/issues
.. _Fetching data and feeds: docs/COOKBOOK.rst#fetching-data-and-feeds

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
