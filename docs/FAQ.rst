riko FAQ
========

This FAQ answers some commonly asked questions. For a progressive tutorial,
view the `README`_ and `Cookbook`_.

Index
-----

- `What is riko's data model`_
- `Which Python versions are supported`_
- `Which imports are public`_
- `What pipes are available`_
- `How do I discover installed modules`_
- `What do processor, operator, and splitter mean`_
- `How does a processor map over items`_
- `What file types are supported`_
- `What protocols are supported`_
- `Which optional dependencies are available`_
- `How do synchronous and asynchronous pipelines differ`_
- `What does parallel=True do`_
- `Is riko distributed`_
- `Why does a pipeline return no items the second time`_
- `Which operations materialize or retain input`_
- `How do I send one stream to multiple consumers`_
- `Can I define a pipeline as JSON`_
- `What execution modes are available for compiled pipelines`_
- `Can I create custom modules`_
- `How should errors and resource cleanup be handled`_
- `Where should I report problems or contribute`_

What is riko's data model?
--------------------------

An ``item`` is a dictionary-like record. A ``stream`` is an iterator of
``item``. A ``pipe`` is a configured module that creates, transforms, combines,
or consumes a ``stream``.

.. code-block:: python

    >>> from riko import SyncPipe, Transforms
    >>>
    >>> items = [{'title': 'alpha'}, {'title': 'beta'}]
    >>> flow = SyncPipe(
    ...     Transforms.HASH, source=items, field='title', assign='title_hash'
    ... )
    >>> len(list(flow))
    2

``riko`` is designed around ordinary Python iteration. It is not a dataframe
engine, distributed runner, durable scheduler, or reactive event system.

Which Python versions are supported?
------------------------------------

``riko`` requires Python 3.12 or newer and is tested on CPython 3.12, 3.13, and
3.14.

The published PyPI release may lag the ``features`` branch. Check
``riko.__version__`` and ``riko.__file__`` when an installed package does not
match repository examples:

.. code-block:: bash

    python -c "import riko; print(riko.__version__, riko.__file__)"

See the `installation guide`_ for release and branch installation commands.

Which imports are public?
-------------------------

``riko`` organizes its public interface into three import tiers:

- **Stable**: the top-level ``riko`` package (mirrored by ``riko.api``) holds the
  SemVer-guaranteed API: the ``SyncPipe``/``AsyncPipe``/``SyncCollection``/
  ``AsyncCollection`` classes, ``Context``, ``ExecutionMode``, ``PipeState``,
  ``backend``, ``build_pipeline``, ``compile_pipe``, ``convert_dag``, ``export``,
  ``extract_dependencies``, ``get_module_metadata``, ``get_path``, ``isasync``,
  ``issync``, ``list_modules``, ``describe_module``, ``list_targets``,
  ``parse_pipe_def``, ``run``, the typed discovery surface (``Modules``/``Sources``/
  ``Transforms``/``Sinks``/``Targets`` bucket enums), and the pipeline exceptions.
- **Extension**: ``riko.ext`` holds the symbols for authoring custom ``pipes``:
  the ``processor``/``operator``/``splitter`` decorators and the module-metadata types.
- **Private**: all import paths outside ``riko``, ``riko.api``, and ``riko.ext``,
  including individual ``riko.modules.*`` implementations and other implementation
  modules.

Application code should import from ``riko`` or ``riko.api``.

.. code-block:: python

    >>> from riko import (
    ...     AsyncCollection,
    ...     AsyncPipe,
    ...     Context,
    ...     ExecutionMode,
    ...     Modules,
    ...     Sinks,
    ...     Sources,
    ...     SyncCollection,
    ...     SyncPipe,
    ...     Targets,
    ...     Transforms,
    ...     describe_module,
    ...     export,
    ...     get_path,
    ...     list_modules,
    ...     list_targets,
    ... )

Extension authors should import decorators and protocols from ``riko.ext``:

.. code-block:: python

    >>> from riko.ext import operator, processor, splitter

Underscore-prefixed modules are private. Individual built-in implementations
under ``riko.modules`` remain useful for direct functional composition, but they
are not the stable application import layer.

What pipes are available?
-------------------------

Overview
^^^^^^^^

``riko`` ships 52 built-in ``pipes``, outlined below [#]_. Runtime discovery is
the authoritative source for a ``pipe``'s type, subtype, sync/async
availability, and loopability.

+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| Pipe name            | Pipe type | Primary sub-type | Pipe description                                                                             |
+======================+===========+==================+==============================================================================================+
| `aggregate`_         | operator  | composer         | performs an arbitrary (user-defined) function on a stream                                    |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `count`_             | operator  | aggregator       | counts the number of items in a feed                                                         |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `csv`_               | processor | source           | parses a CSV file to yield items                                                             |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `currencyformat`_    | processor | transformer      | formats a number to a given currency string                                                  |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `datebuilder`_       | processor | transformer      | converts a text string into a datetime                                                       |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `dateformat`_        | processor | transformer      | formats a date                                                                               |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `exchangerate`_      | processor | transformer      | retrieves the current exchange rate for a given currency pair                                |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `feedautodiscovery`_ | processor | source           | discovers RSS/Atom feed links on a page                                                      |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `fetch`_             | processor | source           | fetches and parses a feed to return the entries                                              |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `fetchdata`_         | processor | source           | fetches and parses an XML or JSON file to return the feed entries                            |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `fetchpage`_         | processor | source           | fetches the content of a given web site as a string                                          |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `fetchsitefeed`_     | processor | source           | fetches and parses the first feed found on a site                                            |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `fetchtable`_        | processor | source           | fetches and parses tabular data (CSV, XLS, JSON, etc.) to yield items                        |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `fetchtext`_         | processor | source           | fetches and parses a text file                                                               |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `filter`_            | operator  | composer         | extracts items matching the given rules                                                      |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `forever`_           | processor | source           | yields an endless stream of empty items (mocks an input source)                              |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `geolocate`_         | processor | transformer      | obtains the geo location of an IP or street address                                          |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `hash`_              | processor | transformer      | hashes the field of a feed item                                                              |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `input`_             | processor | source           | prompts for text and parses it into a variety of different types, e.g., int, bool, date, etc |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `itembuilder`_       | processor | source           | builds an item                                                                               |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `join`_              | operator  | composer         | perform a SQL like join on two feeds                                                         |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `loop`_              | operator  | composer         | runs a submodule (pipe) once per stream item                                                 |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `receive`_           | operator  | composer         | receives stream items from a named channel (pub/sub)                                         |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `refind`_            | processor | transformer      | finds text located before, after, or between substrings using regular expressions            |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `regex`_             | processor | transformer      | replaces text in fields of a feed item using regexes                                         |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `rename`_            | processor | transformer      | renames or copies fields in a feed item                                                      |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `reverse`_           | operator  | composer         | reverses the order of source items in a feed                                                 |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `rssitembuilder`_    | processor | source           | builds an rss item                                                                           |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `send`_              | operator  | composer         | pushes a copy of each stream item to named channels (pub/sub)                                |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `simplemath`_        | processor | transformer      | performs basic arithmetic, such as addition and subtraction                                  |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `slugify`_           | processor | transformer      | slugifies text                                                                               |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `sort`_              | operator  | composer         | sorts a feed according to a specified key                                                    |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `split`_             | splitter  | splitter         | splits a feed into identical copies                                                          |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `strconcat`_         | processor | transformer      | concatenates strings                                                                         |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `strfind`_           | processor | transformer      | finds text located before, after, or between substrings                                      |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `strreplace`_        | processor | transformer      | replaces the text of a field of a feed item                                                  |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `strtransform`_      | processor | transformer      | performs string transformations on the field of a feed item                                  |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `subelement`_        | processor | transformer      | extracts sub-elements for the item of a feed                                                 |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `substr`_            | processor | transformer      | returns a substring of a field of a feed item                                                |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `sum`_               | operator  | aggregator       | sums a field of items in a feed                                                              |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `tail`_              | operator  | composer         | truncates a feed to the last N items                                                         |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `timeout`_           | operator  | composer         | returns items from a stream until a certain amount of time has passed                        |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `tokenizer`_         | processor | transformer      | splits a string by a delimiter                                                               |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `truncate`_          | operator  | composer         | returns a specified number of items from a feed                                              |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `typecast`_          | processor | transformer      | casts a field into a specific type                                                           |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `udf`_               | processor | transformer      | performs an arbitrary (user-defined) function on an item                                     |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `union`_             | operator  | composer         | merges multiple feeds together                                                               |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `uniq`_              | operator  | composer         | filters out non-unique items according to a specified field                                  |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `urlbuilder`_        | processor | transformer      | builds a URL                                                                                 |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `urlparse`_          | processor | transformer      | parses a URL into its six components                                                         |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `write`_             | operator  | composer         | writes the stream to a file; passes items through unchanged (in-pipeline sink)               |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+
| `xpathfetchpage`_    | processor | source           | fetches the content of a given website as DOM nodes or a string                              |
+----------------------+-----------+------------------+----------------------------------------------------------------------------------------------+

Args
^^^^

``riko`` ``pipes`` come in three types: ``processor``, ``operator``, and
``splitter`` [#]_. An ``operator`` operates on a ``stream``. Examples include
``count``, ``filter``, and ``reverse``.

.. code-block:: python

    >>> from riko import SyncPipe, Transforms
    >>>
    >>> stream = [{'title': 'riko pt. 1'}, {'title': 'riko pt. 2'}]
    >>> next(SyncPipe(Transforms.REVERSE, stream))
    {'title': 'riko pt. 2'}

A ``processor`` processes individual ``items``. Examples include ``fetchsitefeed``,
``hash``, ``itembuilder``, and ``regex``.

.. code-block:: python

    >>> from riko import SyncPipe, Transforms
    >>>
    >>> items = [{'title': 'riko pt. 1'}]
    >>> result = next(SyncPipe(Transforms.HASH, items, field='title'))
    >>> sorted(result)
    ['hash', 'title']
    >>> result['hash']
    1104819838

A ``splitter`` returns multiple ``streams`` from one ``stream``. The built-in
example is ``split``.

Kwargs
^^^^^^

The following table outlines the available kwargs.

=========  ====  ==================================================  =======
kwarg      type  description                                         default
=========  ====  ==================================================  =======
conf       dict  The pipe configuration                              varies
extract    str   The key with which to get a value from ``conf``     None
listize    bool  Ensure that an ``extract`` value is list-like       False
pdictize   bool  Convert ``conf``/``extract`` to a DotDict instance  varies
objectify  bool  Convert ``conf`` to an Objectify instance           varies
ptype      str   Used to convert ``conf`` items to a specific type.  pass
dictize    bool  Convert the input ``item`` to a DotDict instance    True
field      str   The key with which to get a value from the input    None
ftype      str   Converts the input ``item`` to a specific type      pass
count      str   The output count                                    all
assign     str   Attribute used to assign output                     varies
emit       bool  Return the output as is (don't assign)              varies
skip_if    func  Determines if processing should be skipped          None
inputs     dict  Values to be used in place of prompting the user    None
=========  ====  ==================================================  =======

Notes

.. [#] See `Design Principles`_ for explanation on `pipe` types and sub-types
.. [#] See `Alternate pipeline creation`_ for pipe composition examples

How do I discover installed modules?
------------------------------------

Use ``list_modules()``. The catalog is derived from the modules installed in
``riko.modules`` and its metadata is read off each implementation.

.. code-block:: python

    >>> from riko import list_modules, list_targets, Modules
    >>>
    >>> list_modules()[0]
    'aggregate'
    >>> len(list_modules())
    52
    >>> # filter by decorator type (`operator`, `processor`, `splitter`)
    >>> list_modules(type='operator')[0]
    'aggregate'
    >>> len(list_modules(type='operator'))
    16
    >>> # filter by ``loopable``
    >>> list_modules(loopable=True)[0]
    'csv'
    >>> len(list_modules(loopable=True))
    34
    >>> # filter by ``subtype``
    >>> list_modules(subtype='aggregator')[0]
    'count'
    >>> len(list_modules(subtype='aggregator'))
    2
    >>> # filter by modules whose default behavior
    >>> list_modules(subtype='composer', primary=True)[0]
    'aggregate'
    >>> len(list_modules(subtype='composer', primary=True))
    14
    >>> # filter by ``category``
    >>> list_modules(category='source')[0]
    'csv'
    >>> len(list_modules(category='source'))
    12
    >>> # Full module metadata
    >>> metadata = list_modules(show_metadata=True)[0]
    >>> metadata.name, metadata.type, metadata.subtype
    ('aggregate', 'operator', 'composer')
    >>> # Available export targets ('ofx'/'qif' only available once installing the
    >>> # ``finance`` extra.)
    >>> list_targets()[0]
    'csv'
    >>> len(list_targets()) >= 5
    True

``describe_module`` returns a ``ModuleDefinition`` (or ``None`` for an unknown name).
Both accept a plain ``str`` or a ``StrEnum`` member.

.. code-block:: python

    >>> write = describe_module(Sinks.WRITE)
    >>> write.name, write.description
    ('write', 'Writes a stream to a file as a terminal sink.')
    >>> fetch = describe_module(Sources.FETCH)
    >>> fetch.module
    <module 'riko.modules.fetch' from '...fetch.py'>
    >>> fetch.sync_pipe.__name__, fetch.async_pipe.__name__
    ('pipe', 'async_pipe')
    >>> describe_module('does-not-exist')

Notes:

- ``type`` accepts ``processor``, ``operator``, or ``splitter``.
- ``subtype`` accepts ``source``, ``transformer``, ``composer``, ``aggregator``, and
  ``splitter``
- ``type`` and ``subtype`` are mutually exclusive: a subtype implies its type.
- Module authors do not declare these metadata attributes; they are derived from the
  decorator type, options, and return annotations.
- The catalog overlays registry entries: modules added via ``riko.ext.register`` or a
  ``[project.entry-points."riko.modules"]`` entry point appear alongside the packaged
  built-ins (see `Can I create custom modules`_).
- ``category`` (``source``/``transform``/``sink``) is a data-flow axis,
  independent of the runtime ``type``/``subtype``.

Typed module discovery
^^^^^^^^^^^^^^^^^^^^^^^

For editor autocompletion and static checks, ``riko`` ships a generated, typed discovery
surface. ``Modules`` is a ``StrEnum`` of **every** built-in ``pipe``, while
``Sources``/``Transforms``/``Sinks``/``Targets`` are a ``StrEnum`` that group by
data-flow role. Each ``StrEnum`` is interchangeable with a module name.

.. code-block:: python

    >>> from riko import Modules, Sources, Transforms, Sinks, Targets
    >>>
    >>> Sources.FETCH.value
    'fetch'
    >>> Sources.FETCH == 'fetch'
    True
    >>> Modules.FETCH is Sources.FETCH
    True
    >>> Modules.FILTER is Transforms.FILTER
    True
    >>> Modules.WRITE is Sinks.WRITE
    True

Notes:

- ``Sinks`` classifies *sink pipes* (data-flow role ``output``/``write``). The one
  built-in is ``write``, which serializes the stream to a file and passes items through
  the remaining pipeline.
- ``write`` takes a ``target`` option which can be a string or ``Targets`` enum. See
  `exporting results`_ for examples.

What do processor, operator, and splitter mean?
-----------------------------------------------

A ``processor`` works on individual ``items``. A ``processor`` whose input type
is ``none`` is a ``source``; other ``processors`` are ``transformers``. Loopable
``processors`` can be mapped over a ``source`` and are the ``pipes`` eligible for
local sync pools or bounded async concurrency.

An ``operator`` works on a whole ``stream``. A ``composer`` returns a
``stream``, while an ``aggregator`` reduces a ``stream`` to a non-stream result
that the wrapper emits as one or more ``items``. Some ``operators`` support both
behaviors depending on options, so use ``subtype`` metadata when classification matters.

A ``splitter`` returns multiple ``streams``. The built-in ``split`` module
eagerly materializes its ``source`` before creating copies.

How does a processor map over items?
------------------------------------

A ``processor``'s first argument is normally one ``item``, but it may also be a
``stream`` of items. ``riko`` normalizes at the stream boundary the same way
``listize`` does: a ``list``, ``tuple``, ``range``, generator, or iterator maps
over each element, while a mapping (one record), primitive, string, or ``None``
is a single ``item``. So the following all behave predictably:

.. code-block:: python

    >>> from riko.modules.udf import pipe
    >>>
    >>> func = lambda item: {"y": item["x"] + 3}
    >>> source = [{"x": 0}, {"x": 1}]
    >>> next(pipe(source[0], func=func))
    {'y': 3}
    >>> next(pipe(iter(source), func=func))
    {'y': 3}
    >>> next(pipe(source, func=func))
    {'y': 3}
    >>> next(pipe(tuple(source), func=func))
    {'y': 3}

Only the outermost argument is interpreted as one-or-many, so a list-valued
*field* inside a record stays a single value:

    >>> item = {"x": 0, "tags": ["a", "b"]}
    >>> next(pipe(item, func=lambda i: {"tags": i["tags"]}))
    {'tags': ['a', 'b']}

The supported ``SyncPipe``/``AsyncPipe`` objects behave identically.

    >>> from riko import SyncPipe, Modules
    >>>
    >>> source = [{"x": 0}, {"x": 1}]
    >>> next(SyncPipe(Modules.UDF, iter(source), func=func))
    {'y': 3}
    >>> next(SyncPipe(Modules.UDF, source, func=func))
    {'y': 3}

What file types are supported?
------------------------------

File types that ``riko`` supports are outlined below. Reader capabilities can
depend on the installed ``meza`` version and the underlying format, so test
representative files before relying on a format in production.

===================  =======================  ===========================================
File type            Recognized extension(s)  Supported pipes
===================  =======================  ===========================================
HTML                 html                     feedautodiscovery, fetchpage, fetchsitefeed
XML                  xml                      fetch, fetchdata
JSON                 json, geojson            fetchdata, fetchtable
Comma/tab separated  csv, tsv                 csv, fetchtable
Excel                xls, xlsx                fetchtable
MS Access            mdb                      fetchtable
dBASE                dbf                      fetchtable
YAML                 yml, yaml                fetchtable
SQLite               sqlite                   fetchtable
Fixed width          fixed                    fetchtable
===================  =======================  ===========================================

What protocols are supported?
-----------------------------

Protocols that ``riko`` supports are outlined below. Remote access is
network-dependent and can fail because of timeouts, authentication, redirects,
rate limits, TLS configuration, or server behavior.

========  =========================================
Protocol  example
========  =========================================
http      http://google.com
https     https://github.com
file      file:///path/to/feed.xml
========  =========================================

Use ``riko.get_path()`` only for package data and repository examples. It is not
a general application data directory.

Which optional dependencies are available?
------------------------------------------

===========  ============================  ======================================
Extra        Packages                      Capability
===========  ============================  ======================================
``async``    AnyIO, httpx                  Asynchronous execution and HTTP paths
``perf``     fastfeedparser, ijson, lxml   Accelerated / streaming parser paths
``finance``  csv2ofx                       OFX and QIF export targets
===========  ============================  ======================================

From a checkout, install an ``extra`` with a quoted, editable command such as
``python -m pip install -e ".[async]"``. Use ``list_targets()`` to discover the export
targets available in the active environment.

How do synchronous and asynchronous pipelines differ?
-----------------------------------------------------

``SyncPipe`` implements ordinary iteration. ``AsyncPipe`` implements async
iteration and can also be awaited. Awaiting materializes all remaining
``items``; ``async for`` preserves item-by-item consumption.

Fully consumed sync and async pipelines are tested for equivalent data output.
Execution mechanics can differ under partial consumption: a loopable ``pipe``
mapped over its ``source`` may begin work for ``items`` that a downstream consumer
never yields. Keep side effects out of such ``pipes`` when consuming partially, or
bound the work per ``item``.

``SyncCollection`` fetches multiple configured sources sequentially or with a
local pool. ``AsyncCollection`` fetches sources concurrently with bounded
in-flight work.

What does ``parallel=True`` do?
-------------------------------

For ``SyncPipe``, eligible item-processing ``pipes`` use a local thread pool by
default. Pass ``threads=False`` to use a process pool. The current sync mapping
path materializes the ``pipe`` ``source`` before dispatch, so it is suitable only
for finite inputs. Results are unordered unless ``ordered=True`` is requested.

For ``AsyncPipe``, ``parallel=True`` enables bounded async concurrency with
backpressure. ``connections`` limits in-flight work, ``prefetch`` controls extra
buffering, and ``ordered=True`` preserves source order.

Parallel execution is not automatically faster. Pool startup, serialization,
network behavior, ordering, and workload size can outweigh concurrency gains.
Measure the actual pipeline.

Is riko distributed?
--------------------

No. ``riko`` runs in one Python process, with optional local threads, local
worker processes, or async tasks. It does not provide cluster runners,
checkpoints, durable retries, event-time windows, a scheduler, or a workflow UI.

Use an orchestrator around ``riko`` when you need durable task execution, and
use a distributed data engine when one machine is insufficient.

Why does a pipeline return no items the second time?
----------------------------------------------------

A ``pipe`` or collection instance represents one execution. Consuming it
advances its underlying iterator. Re-iterating an exhausted or failed instance
returns an empty ``stream`` rather than silently rerunning work.

.. code-block:: python

    >>> from riko import SyncPipe, Transforms
    >>>
    >>> flow = SyncPipe(Transforms.HASH, source=[{'content': 'a'}])
    >>> len(list(flow))
    1
    >>> list(flow)
    []

Build a new pipeline instance to rerun the pipeline. Chaining after partial
consumption wraps the remaining ``source``. Chaining after ``close()`` or
failure raises ``PipelineStateError``.

Which operations materialize or retain input?
---------------------------------------------

Don't assume every ``pipe`` is fully streaming. Some read the whole ``stream`` in
memory, so they cannot be used on an unbounded source. The table below records what each
retains.

===========  ================  =======================================================
pipe         retains           why
===========  ================  =======================================================
``write``    whole ``stream``  Serializing needs every ``item``, so the source is
                               materialized before the write; the items it passes
                               through are replayed from that list.
``split``    whole ``stream``  Copies a materialized finite ``stream`` to each branch.
``sort``     whole ``stream``  ``sorted()`` cannot rank a partial ``stream``.
``reverse``  whole ``stream``  The last ``item`` must be known before the first is
                               emitted.
``count``    whole ``stream``  Counts the materialized ``stream``, and groups every
                               ``item`` when ``count_key`` is set.
``sum``      group only        Streams in O(1) memory without ``group_key``; retains
                               every ``item`` when grouping.
``join``     the ``other``     The right-hand side is replayed against each left
                               ``item``.
``tail``     last N            Bounded by ``conf['count']``.
``uniq``     last N keys       Bounded by ``conf['limit']``.
===========  ================  =======================================================

``export()`` and serialized exports materialize by the same reasoning as ``write``.
Awaiting an ``AsyncPipe`` materializes all remaining ``items``, and
``SyncPipe(parallel=True)``/``SyncCollection(parallel=True)`` materialize the source
before submission.

``AsyncPipe(parallel=True)`` uses bounded concurrency instead of materializing the
source, though it still keeps in-flight and optionally prefetched work. Without
``parallel`` it buffers the source instead. ``AsyncCollection`` ignores ``parallel``.
It bounds by ``connections``, and streams incrementally (unless ``ordered=True``,
in which case it fetches each source whole). See the `Cookbook`_'s performance and
memory section for practical guidance.

How do I send one stream to multiple consumers?
-----------------------------------------------

Use ``split`` for the simplest finite-stream copy. It eagerly materializes the
entire ``source`` and returns identical iterators.

Use ``send`` and ``receive`` for lazy in-process fan-out. Receivers must be
created and primed before the sender is consumed. Consuming the main sender
drives delivery to each named channel. This is an in-process coordination
mechanism, not an external message broker.

The `Cookbook`_ fan-out section include complete recipes for both approaches.

Can I define a pipeline as JSON?
--------------------------------

``riko`` ships two commands for working with JSON pipe definitions (the
Yahoo! Pipes-style ``{"modules": [...], "wires": [...]}`` format):

- ``compile-pipe`` translates a JSON pipe definition into a runnable Python module.
- ``convert-dag`` expands a *bare-bones DAG* into a full JSON pipe definition.

A bare-bones DAG is a minimal authoring format: a list of ``modules``
(``id``/``type``/``conf``) plus optional ``[source, target]`` wire pairs. When
``wires`` are omitted the modules are chained linearly, and a missing ``id``
defaults to ``sw-{n}``, so the terse form is just:

.. code-block:: json

    {
        "modules": [
            {"type": "fetchdata", "conf": {"url": "feed.json", "path": "value.items"}},
            {"type": "truncate", "conf": {"count": {"value": "3"}}}
        ]
    }

Compact ``[source, target]`` pairs can't represent the secondary fan-in ports
for modules such as ``join`` and ``union``. Use the full format for those. Chaining
``compile-pipe`` and ``convert-dag`` turns a DAG straight into runnable Python (both
write to stdout, or to a file via ``-o``):

.. code-block:: bash

    convert-dag flow.dag.json -o flow.json
    compile-pipe flow.json -o flow.py


See the `DAG format`_ doc and the `Cookbook`_ for the full format/expansion rules and
examples.

What execution modes are available for compiled pipelines?
----------------------------------------------------------

``Context`` accepts these ``ExecutionMode`` values:

=======================  =========================================================
Mode                     Behavior
=======================  =========================================================
RUN                      Execute the normal pipeline (the default)
DESCRIBE_INPUTS          Return declared input requirements instead of running
DESCRIBE_DEPENDENCIES    Return module dependencies
DESCRIBE                 Return both input and dependency information
=======================  =========================================================

``extract_dependencies()`` can also inspect a pipe definition without executing
it. See `Inspecting a pipeline`_ in the cookbook for additional details.

The chainable classes share one pipeline model across four execution styles.

+------------------------------+----------------------------------------+------------------------------------------------+
| API / mode                   | How it runs                            | Important behavior                             |
+==============================+========================================+================================================+
| ``SyncPipe``                 | inline iterator pipeline               | single-use; lazy except sort/aggregate         |
+------------------------------+----------------------------------------+------------------------------------------------+
| ``SyncPipe(parallel=True)``  | local thread (or process) pool         | eligible pipes; source materialized first      |
+------------------------------+----------------------------------------+------------------------------------------------+
| ``AsyncPipe``                | async iteration or ``await``           | await materializes; mapped source runs eager   |
+------------------------------+----------------------------------------+------------------------------------------------+
| ``AsyncPipe(parallel=True)`` | bounded async concurrency              | tune ``connections``/``prefetch``/``ordered``  |
+------------------------------+----------------------------------------+------------------------------------------------+
| ``SyncCollection``           | fetch sources sequentially or pooled   | sources may pick a pipe via ``type``           |
+------------------------------+----------------------------------------+------------------------------------------------+
| ``AsyncCollection``          | fetch sources concurrently             | bounded, optionally ordered                    |
+------------------------------+----------------------------------------+------------------------------------------------+

Can I create custom modules?
----------------------------

Yes. ``riko.ext`` exposes ``processor``, ``operator``, and ``splitter``
decorators plus supported protocols and metadata types. Decorated functions can
be called directly and composed with ordinary Python.

To make a module resolvable by name (so ``SyncPipe('your.module', ...)`` and the
``|`` operator can find it), register it with the module registry. Package your
module so it exposes ``pipe`` and/or ``async_pipe`` functions, then either register
it at runtime or declare an entry point.

Entry point (discovered lazily; no edit to riko core, nothing imported until the
name is resolved):

.. code-block:: python

    # your_ext/modules.py
    from riko.ext import ModuleDefinition
    from your_ext import shout  # a module exposing pipe/async_pipe

    shout_definition = ModuleDefinition(module=shout, description="Uppercase 'content'.")

.. code-block:: toml

    # pyproject.toml
    [project.entry-points."riko.modules"]
    "example.shout" = "your_ext.modules:shout_definition"

Runtime registration (process-global; precedence is runtime → entry point →
built-in):

.. code-block:: python

    from riko.ext import ModuleDefinition, register

    register(ModuleDefinition(name="example.shout", module=shout))

Point ``module`` at an object exposing ``pipe``/``async_pipe``, or pass
``sync_pipe``/``async_pipe`` explicitly for a bare callable. Registered and
entry-point names surface in ``list_modules()`` alongside the packaged built-ins.
See ``examples/riko-example-ext`` for a complete, installable example, the
`Cookbook`_ for custom ``processor`` and ``operator`` examples, and the
`contributing guide`_ for the additional work required for a built-in module.

How should errors and resource cleanup be handled?
--------------------------------------------------

Normal module exceptions propagate. A failing ``pipe`` records the ``FAILED``
state, and a closed ``pipe`` records ``CLOSED``. Use ``state``, ``failed``,
``closed``, and ``exhausted`` for inspection.

Use sync parallel ``pipes`` and collections as context managers when you need
deterministic worker-pool cleanup. Use ``async with`` or ``aclose()`` for early
async termination. External I/O can still raise the normal network, parser, and
filesystem exceptions for the underlying operation.

Where should I report problems or contribute?
---------------------------------------------

Use the `issue tracker`_ for reproducible bugs and focused proposals. See the
`contributing guide`_ for the current uv setup, test, lint, type-check, tox, and
documentation workflow.

.. _What is riko's data model: #what-is-rikos-data-model
.. _Which Python versions are supported: #which-python-versions-are-supported
.. _Which imports are public: #which-imports-are-public
.. _What pipes are available: #what-pipes-are-available
.. _How do I discover installed modules: #how-do-i-discover-installed-modules
.. _What do processor, operator, and splitter mean: #what-do-processor-operator-and-splitter-mean
.. _How does a processor map over items: #how-does-a-processor-map-over-items
.. _What file types are supported: #what-file-types-are-supported
.. _What protocols are supported: #what-protocols-are-supported
.. _Which optional dependencies are available: #which-optional-dependencies-are-available
.. _How do synchronous and asynchronous pipelines differ: #how-do-synchronous-and-asynchronous-pipelines-differ
.. _What does parallel=True do: #what-does-paralleltrue-do
.. _Is riko distributed: #is-riko-distributed
.. _Why does a pipeline return no items the second time: #why-does-a-pipeline-return-no-items-the-second-time
.. _Which operations materialize or retain input: #which-operations-materialize-or-retain-input
.. _How do I send one stream to multiple consumers: #how-do-i-send-one-stream-to-multiple-consumers
.. _Can I define a pipeline as JSON: #can-i-define-a-pipeline-as-json
.. _What execution modes are available for compiled pipelines: #what-execution-modes-are-available-for-compiled-pipelines
.. _Can I create custom modules: #can-i-create-custom-modules
.. _How should errors and resource cleanup be handled: #how-should-errors-and-resource-cleanup-be-handled
.. _Where should I report problems or contribute: #where-should-i-report-problems-or-contribute
.. _Inspecting a pipeline: COOKBOOK.rst#inspecting-a-pipeline

.. _README: ../README.rst
.. _Cookbook: COOKBOOK.rst
.. _exporting results: COOKBOOK.rst#exporting-results
.. _installation guide: INSTALLATION.rst
.. _contributing guide: ../CONTRIBUTING.rst
.. _issue tracker: https://github.com/nerevu/riko/issues
.. _DAG format: DAG_FORMAT.rst
.. _Design Principles: ../README.rst#design-principles
.. _Alternate pipeline creation: COOKBOOK.rst#alternate-pipeline-creation

.. _aggregate: ../riko/modules/aggregate.py
.. _count: ../riko/modules/count.py
.. _csv: ../riko/modules/csv.py
.. _currencyformat: ../riko/modules/currencyformat.py
.. _datebuilder: ../riko/modules/datebuilder.py
.. _dateformat: ../riko/modules/dateformat.py
.. _exchangerate: ../riko/modules/exchangerate.py
.. _feedautodiscovery: ../riko/modules/feedautodiscovery.py
.. _fetch: ../riko/modules/fetch.py
.. _fetchdata: ../riko/modules/fetchdata.py
.. _fetchpage: ../riko/modules/fetchpage.py
.. _fetchsitefeed: ../riko/modules/fetchsitefeed.py
.. _fetchtable: ../riko/modules/fetchtable.py
.. _fetchtext: ../riko/modules/fetchtext.py
.. _filter: ../riko/modules/filter.py
.. _forever: ../riko/modules/forever.py
.. _geolocate: ../riko/modules/geolocate.py
.. _hash: ../riko/modules/hash.py
.. _input: ../riko/modules/input.py
.. _itembuilder: ../riko/modules/itembuilder.py
.. _join: ../riko/modules/join.py
.. _loop: ../riko/modules/loop.py
.. _receive: ../riko/modules/receive.py
.. _refind: ../riko/modules/refind.py
.. _regex: ../riko/modules/regex.py
.. _rename: ../riko/modules/rename.py
.. _reverse: ../riko/modules/reverse.py
.. _rssitembuilder: ../riko/modules/rssitembuilder.py
.. _send: ../riko/modules/send.py
.. _simplemath: ../riko/modules/simplemath.py
.. _slugify: ../riko/modules/slugify.py
.. _sort: ../riko/modules/sort.py
.. _split: ../riko/modules/split.py
.. _strconcat: ../riko/modules/strconcat.py
.. _strfind: ../riko/modules/strfind.py
.. _strreplace: ../riko/modules/strreplace.py
.. _strtransform: ../riko/modules/strtransform.py
.. _subelement: ../riko/modules/subelement.py
.. _substr: ../riko/modules/substr.py
.. _sum: ../riko/modules/sum.py
.. _tail: ../riko/modules/tail.py
.. _timeout: ../riko/modules/timeout.py
.. _tokenizer: ../riko/modules/tokenizer.py
.. _truncate: ../riko/modules/truncate.py
.. _typecast: ../riko/modules/typecast.py
.. _udf: ../riko/modules/udf.py
.. _union: ../riko/modules/union.py
.. _uniq: ../riko/modules/uniq.py
.. _urlbuilder: ../riko/modules/urlbuilder.py
.. _urlparse: ../riko/modules/urlparse.py
.. _write: ../riko/modules/write.py
.. _xpathfetchpage: ../riko/modules/xpathfetchpage.py
