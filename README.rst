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
stream processors aka ``workflows``.

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

    >>> from riko import get_path, SyncPipe
    >>>
    >>> ### Set the pipe configurations ###
    >>> #
    >>> # Notes:
    >>> #   1. look up cached file in the `data` directory
    >>> #   2. fetch the text contained inside the 'body' tag of a web page and strip
    >>> #      html tags
    >>> #   3. replace newlines with spaces and assign the result to 'content'
    >>> #   4. tokenize the resulting text using whitespace as the delimiter
    >>> #   5. count the number of times each token appears
    >>>
    >>> url = get_path('users.jyu.fi.html')                   # 1
    >>> fetch_conf = {'url': url, 'start': '<body>', 'end': '</body>', 'detag': True}
    >>> replace_conf = {
    ...     'rule': [{'find': '\r\n', 'replace': ' '}, {'find': '\n', 'replace': ' '}]
    ... }
    >>>
    >>> flow = (
    ...     SyncPipe('fetchpage', conf=fetch_conf)            # 2
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

I wanted a small-footprint, pure-Python library for processing data streams. I wanted
to fetch RSS feeds and perform custom transformations without the complexities of
distributed compute engines, workflow schedulers, clusters, or message queues.

``riko``, a primarily pull-based in-process library, is the result.

Why you should use riko
^^^^^^^^^^^^^^^^^^^^^^^

``riko`` provides a number of benefits / differences from other stream processing
applications:

- a small footprint (CPU and memory usage)
- native RSS/Atom support
- simple installation and usage
- a pure Python library supporting v3.12+
- built-in modular ``pipes`` to filter, sort, and modify ``streams``

Why you shouldn't use riko
^^^^^^^^^^^^^^^^^^^^^^^^^^

``riko`` is usually not the right tool when you need: distributed execution,
durable scheduling, automatic retries, continual data monitoring, a workflow UI,
event-triggered actions, or query optimization.

Choosing riko
^^^^^^^^^^^^^

The projects below overlap with `riko` in different ways. Some are embedded
libraries, while others are distributed engines, workflow orchestrators, or
data-integration platforms. RSS/Atom role distinguishes first-party feed support from
functionality that requires a custom source, connector, tap, or task.

+-------------------+----------------------+------------------+----------------------+---------------------------+
| Project           | Primary model        | Deployment       | RSS/Atom             | Best fit                  |
+===================+======================+==================+======================+===========================+
| riko              | Python pipelines     | Embedded, local  | Built in             | Lightweight data and feed |
|                   |                      | process          |                      | processing                |
+-------------------+----------------------+------------------+----------------------+---------------------------+
| RxPY              | Reactive observables | Embedded library | Custom adapter       | Push-based application    |
|                   |                      |                  |                      | events                    |
+-------------------+----------------------+------------------+----------------------+---------------------------+
| Huginn            | Persistent agents    | Self-hosted app  | Built in             | UI-driven monitoring and  |
|                   |                      |                  |                      | automation                |
+-------------------+----------------------+------------------+----------------------+---------------------------+
| Apache Beam       | Portable pipelines   | Runner-dependent | Custom I/O           | Portable batch and stream |
|                   |                      |                  |                      | processing                |
+-------------------+----------------------+------------------+----------------------+---------------------------+
| Flink             | Stateful streams     | Distributed      | Custom connector     | Low-latency, stateful     |
|                   |                      | engine           |                      | processing                |
+-------------------+----------------------+------------------+----------------------+---------------------------+
| Storm             | Event topologies     | Distributed      | Custom spout         | Low-latency event         |
|                   |                      | engine           |                      | processing                |
+-------------------+----------------------+------------------+----------------------+---------------------------+
| Spark             | DataFrame streams    | Distributed      | Custom connector     | Large-scale streaming     |
|                   |                      | engine           |                      | analytics                 |
+-------------------+----------------------+------------------+----------------------+---------------------------+
| Luigi / Prefect   | Task workflows       | Scheduler and    | External task        | Scheduling, retries, and  |
|                   |                      | workers          |                      | dependencies              |
+-------------------+----------------------+------------------+----------------------+---------------------------+
| Airbyte / Meltano | ELT platforms        | Connectors or    | Connector/tap        | Data integration and      |
|                   |                      | plugins          | dependent            | repeatable ELT pipelines  |
+-------------------+----------------------+------------------+----------------------+---------------------------+

Choose `riko` when a pipeline should run directly inside a Python application
without a separate scheduler, service, or cluster. It provides first-party
RSS/Atom processing and supports synchronous, asynchronous, and thread-pooled
local execution.

Choose `RxPY`_ for reactive event composition, `Huginn`_ for persistent
UI-managed automation, and `Flink`_, `Storm`_, `Spark`_, or `Apache Beam`_ when
distributed execution is required. Luigi and Prefect orchestrate tasks, while Airbyte
and Meltano focus on data-integration workflows. Meltano commonly runs Singer taps and
targets and can add scheduling through an orchestration plugin. These tools may
run ``riko`` as one step in a larger workflow rather than replace its in-process
transformation API.

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

    >>> from riko import SyncPipe
    >>>
    >>> items = [{'title': 'riko pt. 1'}, {'title': 'riko pt. 2'}]
    >>> stream = SyncPipe('reverse', items)
    >>> next(stream)
    {'title': 'riko pt. 2'}

A ``processor`` processes an individual ``item`` and can be parallelized across
threads or processes. E.g., ``fetchsitefeed``, ``hash``, ``itembuilder``, and ``regex``.

.. code-block:: python

    >>> from riko import SyncPipe
    >>>
    >>> items = [{'title': 'riko pt. 1'}]
    >>> stream = SyncPipe('hash', items, field='title')
    >>> next(stream)['hash']
    1104819838

Some ``processors``, e.g., ``tokenizer``, return multiple results.

.. code-block:: python

    >>> from riko import SyncPipe
    >>>
    >>> items = [{'title': 'riko pt. 1'}]
    >>> stream = SyncPipe('tokenizer', items, conf={'delimiter': ' '}, field='title')
    >>> list(stream)
    [{'content': 'riko'}, {'content': 'pt.'}, {'content': '1'}]

``operators`` are split into sub-types: ``aggregator``
and ``composer``. ``aggregators``, e.g., ``count``, combine
all ``items`` of an input ``stream`` into a new ``stream`` with a single ``item``;
while ``composers``, e.g., ``filter``, create a new ``stream`` containing
some or all ``items`` of an input ``stream``.

.. code-block:: python

    >>> from riko import SyncPipe
    >>>
    >>> items = [{'title': 'riko pt 1'}, {'title': 'riko pt 2'}]
    >>> list(SyncPipe('count', items))
    [{'count': 2}]

Astute observers may have noticed from the "Word Count" example up top, that ``count``
can return multiple items if you pass in the ``count_key`` config option.

.. code-block:: python

    >>> from riko import SyncPipe
    >>>
    >>> stream = SyncPipe('count', items, conf={'count_key': 'title'})
    >>> list(stream)
    [{'riko pt 1': 1}, {'riko pt 2': 1}]

``processors`` are parallelizable and split into sub-types of ``source`` and
``transformer``. A ``source``, e.g., ``itembuilder``, can create a ``stream``, while
a ``transformer``, e.g. ``hash`` can only transform a source ``item``.

.. code-block:: python

    >>> from riko import SyncPipe
    >>>
    >>> attrs = {'key': 'title', 'value': 'riko pt. 1'}
    >>> next(SyncPipe('itembuilder', conf={'attrs': attrs}))
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
view the `FAQ`_ for steps on runtime discovery via `discovering modules`_

If you are unsure of the type of ``pipe`` you have, check its metadata.

.. code-block:: python

    >>> from riko import get_module_metadata
    >>>
    >>> metadata = get_module_metadata('fetchpage')
    >>> metadata.name, metadata.type, metadata.subtype
    ('fetchpage', 'processor', 'source')
    >>> metadata = get_module_metadata('count')
    >>> metadata.name, metadata.type, metadata.subtype
    ('count', 'operator', 'aggregator')

``SyncPipe``/``AsyncPipe`` perform this check for you to allow for convenient method
chaining and transparent parallelization.

.. code-block:: python

    >>> from riko import SyncPipe
    >>>
    >>> attrs = [
    ...     {'key': 'title', 'value': 'riko pt. 1'},
    ...     {'key': 'content', 'value': "Let's talk about riko!"}
    ... ]
    >>> flow = SyncPipe('itembuilder', conf={'attrs': attrs}).hash()
    >>> item = next(flow)
    >>> item['title'], item['content'], item['hash']
    ('riko pt. 1', "Let's talk about riko!", 197222720)

The ``|`` operator chains the same way, taking a module name or a
``(name, conf)`` tuple — handy when the next ``pipe``'s name is computed:

.. code-block:: python

    >>> from riko import SyncPipe
    >>>
    >>> attrs = [
    ...     {'key': 'title', 'value': 'riko pt. 1'},
    ...     {'key': 'content', 'value': "Let's talk about riko!"}
    ... ]
    >>> item = next(SyncPipe('itembuilder', conf={'attrs': attrs}) | 'hash')
    >>> item['title'], item['hash']
    ('riko pt. 1', 197222720)

View the `Cookbook`_ for advanced examples including how to wire in
values from other pipes or accept user input.

Note: ``type`` and ``subtype`` are mutually exclusive: a subtype implies its type.

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

    >>> from riko import get_path, SyncPipe
    >>>
    >>> stream = SyncPipe('fetch', conf={'url': get_path('feed.xml')})
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

    >>> from riko import get_path, SyncPipe
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
    ...     SyncPipe('fetch', conf=fetch_conf)         # 1
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

    >>> from riko import get_path, SyncPipe
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
    ...     SyncPipe('fetch', conf=fetch_conf, parallel=True, workers=4)  # 1
    ...     .filter(conf={'rule': filter_rule})                           # 2
    ... )
    >>>
    >>> sorted(item['title'] for item in flow)[:3]
    ['Donations', 'FAQ', 'General Comments']

Notes

.. [#] You can instead enable a ``ProcessPool`` by additionally passing ``threads=False`` to ``SyncPipe``, i.e., ``SyncPipe('fetch', conf={'url': url}, parallel=True, threads=False)``.

Asynchronous processing
^^^^^^^^^^^^^^^^^^^^^^^

To enable asynchronous processing, you must install the ``async`` extra.

.. code-block:: bash

    python -m pip install "riko[async]"

.. code-block:: python

    >>> from riko import AsyncPipe, get_path, issync, run
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
    ...         AsyncPipe('fetch', conf=fetch_conf)                 # 1
    ...             .filter(conf={'rule': filter_rule}))            # 2
    ...
    ...     print(next(stream)['title'])
    >>>
    >>> print('Donations') if issync else run(main)
    Donations

Built-in pipes
^^^^^^^^^^^^^^

``riko`` ships `51 built-in`_ ``pipes``. The table below summarizes them.

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

Pipeline lifecycle
^^^^^^^^^^^^^^^^^^

``SyncPipe``/``AsyncPipe`` represent a *single* execution: iterating one
consumes the ``stream``, and iterating it again yields an empty ``stream``. Read the
``state``/``exhausted``/``closed``/``failed`` properties to inspect a pipe. Use it as a
context manager (or call ``close()``/``terminate()``) to release a parallel pipe's
worker pool deterministically.

.. code-block:: python

    >>> from riko import SyncPipe
    >>>
    >>> flow = SyncPipe('hash', source=[{'content': 'a'}, {'content': 'b'}])
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

``riko`` provides a command, ``run-pipe``, to execute ``workflows``. A
``workflow`` is simply a file containing a function named ``pipe`` that creates
a ``flow`` and processes the resulting ``stream``. E.g., ``flow.py``

.. code-block:: python

    from riko import SyncPipe

    conf1 = {'attrs': [{'value': 'https://google.com', 'key': 'content'}]}
    conf2 = {'rule': [{'find': 'com', 'replace': 'co.uk'}]}

    def pipe(test=False):
        kwargs = {'conf': conf1, 'test': test}
        flow = SyncPipe('itembuilder', **kwargs).strreplace(conf=conf2)
        for i in flow:
            print(i)

CLI Usage

  usage: run-pipe [pipeid] [-p PATH]

  description: Runs a riko pipe

  positional arguments:
    pipeid            The workflow to run from the examples directory.

  optional arguments:
    -h, --help        show this help message and exit
    -p, --path PATH   Path to a pipe file to run, e.g. flow.py.
    -a, --async       Load async pipe.
    -t, --test        Run in test mode (uses default inputs).

Now to execute ``flow.py``, type the command ``run-pipe --path flow.py``. You should
then see the following output in your terminal:

.. code-block:: bash

    {'content': 'https://google.com', 'strreplace': 'https://google.co.uk'}

``run-pipe`` will also search the ``examples`` directory for ``workflows``. Type
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
- `DAG format`_ — compact and full JSON ``workflow`` formats
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
.. _51 built-in: docs/FAQ.rst#what-pipes-are-available
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
.. _Huginn: https://github.com/cantino/huginn/
.. _Flink: http://flink.apache.org/
.. _Spark: http://spark.apache.org/streaming/
.. _Storm: http://storm.apache.org/
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
