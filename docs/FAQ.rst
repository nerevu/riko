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
- `What file types are supported`_
- `What protocols are supported`_
- `Which optional dependencies are available`_
- `How do synchronous and asynchronous pipelines differ`_
- `What does parallel=True do`_
- `Is riko distributed`_
- `Why does a pipeline return no items the second time`_
- `Which operations materialize or retain input`_
- `How do I send one stream to multiple consumers`_
- `Can I define a workflow as JSON`_
- `What execution modes are available for compiled workflows`_
- `Can I create custom modules`_
- `How should errors and resource cleanup be handled`_
- `Where should I report problems or contribute`_

What is riko's data model?
--------------------------

An ``item`` is a dictionary-like record. A ``stream`` is an iterator of
``items``. A ``pipe`` is a configured module that creates, transforms, combines,
or consumes a ``stream``.

.. code-block:: python

    >>> from riko import SyncPipe
    >>>
    >>> items = [{'title': 'alpha'}, {'title': 'beta'}]
    >>> flow = SyncPipe('hash', source=items, field='title', assign='title_hash')
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

- **Stable** — the top-level ``riko`` package (mirrored by ``riko.api``) holds the
  SemVer-guaranteed API: the ``SyncPipe``/``AsyncPipe``/``SyncCollection``/
  ``AsyncCollection`` classes, ``Context``, ``ExecutionMode``, ``export``,
  ``list_modules``, ``list_targets``, ``get_path``, and the pipeline exceptions.
- **Extension** — ``riko.ext`` holds the symbols for authoring custom ``pipes``:
  the ``processor``/``operator``/``splitter`` decorators and the module-metadata types.
- **Private** — every underscore-prefixed name or module (and the individual
  ``riko.modules.*`` implementations) is internal and may change without notice.

Application code should import from ``riko`` or ``riko.api``.

.. code-block:: python

    >>> from riko import (
    ...     AsyncCollection,
    ...     AsyncPipe,
    ...     Context,
    ...     ExecutionMode,
    ...     SyncCollection,
    ...     SyncPipe,
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

``riko`` ships 51 built-in ``pipes``, outlined below [#]_. Runtime discovery is
the authoritative source for a ``pipe``'s type, subtype, sync/async
availability, and loopability.

+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| Pipe name            | Pipe type | Pipe sub-type | Pipe description                                                                             |
+======================+===========+===============+==============================================================================================+
| `aggregate`_         | operator  | aggregator    | performs an arbitrary (user-defined) function on a stream                                    |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `count`_             | operator  | aggregator    | counts the number of items in a feed                                                         |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `csv`_               | processor | source        | parses a csv file to yield items                                                             |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `currencyformat`_    | processor | transformer   | formats a number to a given currency string                                                  |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `datebuilder`_       | processor | transformer   | converts a text string into a datetime                                                       |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `dateformat`_        | processor | transformer   | formats a date                                                                               |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `exchangerate`_      | processor | transformer   | retrieves the current exchange rate for a given currency pair                                |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `feedautodiscovery`_ | processor | source        | fetches and parses the first feed found on a site                                            |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `fetch`_             | processor | source        | fetches and parses a feed to return the entries                                              |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `fetchdata`_         | processor | source        | fetches and parses an XML or JSON file to return the feed entries                            |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `fetchpage`_         | processor | source        | fetches the content of a given web site as a string                                          |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `fetchsitefeed`_     | processor | source        | fetches and parses the first feed found on a site                                            |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `fetchtable`_        | processor | source        | fetches and parses tabular data (csv, xls, json, etc.) to yield items                        |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `fetchtext`_         | processor | source        | fetches and parses a text file                                                               |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `filter`_            | operator  | composer      | extracts items matching the given rules                                                      |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `forever`_           | processor | source        | yields an endless stream of empty items (mocks an input source)                              |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `geolocate`_         | processor | transformer   | obtains the geo location of an ip or street address                                          |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `hash`_              | processor | transformer   | hashes the field of a feed item                                                              |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `input`_             | processor | source        | prompts for text and parses it into a variety of different types, e.g., int, bool, date, etc |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `itembuilder`_       | processor | source        | builds an item                                                                               |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `join`_              | operator  | aggregator    | perform a SQL like join on two feeds                                                         |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `loop`_              | operator  | composer      | runs a submodule (pipe) once per stream item                                                 |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `receive`_           | operator  | composer      | receives stream items from a named channel (pub/sub)                                         |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `refind`_            | processor | transformer   | finds text located before, after, or between substrings using regular expressions            |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `regex`_             | processor | transformer   | replaces text in fields of a feed item using regexes                                         |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `rename`_            | processor | transformer   | renames or copies fields in a feed item                                                      |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `reverse`_           | operator  | composer      | reverses the order of source items in a feed                                                 |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `rssitembuilder`_    | processor | source        | builds an rss item                                                                           |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `send`_              | operator  | composer      | pushes a copy of each stream item to named channels (pub/sub)                                |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `simplemath`_        | processor | transformer   | performs basic arithmetic, such as addition and subtraction                                  |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `slugify`_           | processor | transformer   | slugifies text                                                                               |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `sort`_              | operator  | composer      | sorts a feed according to a specified key                                                    |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `split`_             | splitter  | splitter      | splits a feed into identical copies                                                          |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `strconcat`_         | processor | transformer   | concatenates strings                                                                         |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `strfind`_           | processor | transformer   | finds text located before, after, or between substrings                                      |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `strreplace`_        | processor | transformer   | replaces the text of a field of a feed item                                                  |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `strtransform`_      | processor | transformer   | performs string transformations on the field of a feed item                                  |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `subelement`_        | processor | transformer   | extracts sub-elements for the item of a feed                                                 |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `substr`_            | processor | transformer   | returns a substring of a field of a feed item                                                |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `sum`_               | operator  | aggregator    | sums a field of items in a feed                                                              |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `tail`_              | operator  | composer      | truncates a feed to the last N items                                                         |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `timeout`_           | operator  | composer      | returns items from a stream until a certain amount of time has passed                        |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `tokenizer`_         | processor | transformer   | splits a string by a delimiter                                                               |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `truncate`_          | operator  | composer      | returns a specified number of items from a feed                                              |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `typecast`_          | processor | transformer   | casts a field into a specific type                                                           |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `udf`_               | processor | transformer   | performs an arbitrary (user-defined) function on an item                                     |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `union`_             | operator  | composer      | merges multiple feeds together                                                               |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `uniq`_              | operator  | composer      | filters out non unique items according to a specified field                                  |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `urlbuilder`_        | processor | transformer   | builds a url                                                                                 |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `urlparse`_          | processor | transformer   | parses a URL into its six components                                                         |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `xpathfetchpage`_    | processor | source        | fetches the content of a given website as DOM nodes or a string                              |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+

Args
^^^^

``riko`` ``pipes`` come in two flavors; ``operator`` and ``processor`` [#]_.
``operator``s operate on an entire ``stream`` at once. Example ``operator``s
include ``count``, ``filter``, and ``reverse``.

.. code-block:: python

    >>> from riko.modules.reverse import pipe
    >>>
    >>> stream = [{'title': 'riko pt. 1'}, {'title': 'riko pt. 2'}]
    >>> next(pipe(stream))
    {'title': 'riko pt. 2'}

``processor``s process individual ``items``. Example ``processor``s include
``fetchsitefeed``, ``hash``, ``itembuilder``, and ``regex``.

.. code-block:: python

    >>> from riko.modules.hash import pipe
    >>>
    >>> item = {'title': 'riko pt. 1'}
    >>> result = next(pipe(item, field='title'))
    >>> sorted(result)
    ['hash', 'title']
    >>> isinstance(result['hash'], int)
    True

Kwargs
^^^^^^

The following table outlines the available kwargs.

==========  ====  ================================================  =======
kwarg       type  description                                       default
==========  ====  ================================================  =======
conf        dict  The pipe configuration                            varies
extract     str   The key with which to get a value from `conf`     None
listize     bool  Ensure that an `extract` value is list-like       False
pdictize    bool  Convert `conf` / `extract` to a DotDict instance  varies
objectify   bool  Convert `conf` to an Objectify instance           varies
ptype       str   Used to convert `conf` items to a specific type.  pass
dictize     bool  Convert the input `item` to a DotDict instance    True
field       str   The key with which to get a value from the input  None
ftype       str   Converts the input `item` to a specific type      pass
count       str   The output count                                  all
assign      str   Attribute used to assign output                   varies
emit        bool  Return the output as is (don't assign)            varies
skip_if     func  Determines if processing should be skipped        None
inputs      dict  Values to be used in place of prompting the user  None
==========  ====  ================================================  =======

Notes
^^^^^

.. [#] See `Design Principles`_ for explanation on `pipe` types and sub-types
.. [#] See `Alternate workflow creation`_ for pipe composition examples

How do I discover installed modules?
------------------------------------

Use ``list_modules()``. The catalog is derived from the modules installed in
``riko.modules`` and its metadata is read off each implementation.

.. code-block:: python

    >>> from riko import list_modules, list_targets
    >>>
    >>> # filter by decorator type (`operator`, `processor`, `splitter`)
    >>> list_modules()[0]
    'aggregate'
    >>> len(list_modules())
    51
    >>> list_modules(type='operator')[0]
    'aggregate'
    >>> len(list_modules(type='operator'))
    15
    >>> # filter by `loopable`
    >>> list_modules(loopable=True)[0]
    'csv'
    >>> len(list_modules(loopable=True))
    34
    >>> # filter by `supported_subtypes`
    >>> list_modules(subtype='aggregator')[0]
    'count'
    >>> len(list_modules(subtype='aggregator'))
    2
    >>> # Only modules whose default behavior is aggregation (`primary=True` requires
    >>> # `subtype`)
    >>> list_modules(subtype='aggregator', primary=True)[0]
    'count'
    >>> len(list_modules(subtype='aggregator', primary=True))
    2
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

Notes:

- ``type`` accepts ``processor``, ``operator``, or ``splitter``.
- ``subtype`` accepts ``source``, ``transformer``, ``composer``, ``aggregator``, and
  ``splitter``
- ``type`` and ``subtype`` are mutually exclusive: a subtype implies its type.
- ``supported_subtypes`` includes behaviors reachable through options such as
  ``emit=True``.
- Module authors do not declare these metadata attributes; they are derived from the
  decorator type, options, and return annotations.

What do processor, operator, and splitter mean?
-----------------------------------------------

A ``processor`` works on individual ``items``. A ``processor`` whose input type
is ``none`` is a ``source``; other ``processors`` are ``transformers``. Loopable
``processors`` can be mapped over a ``source`` and are the stages eligible for
local sync pools or bounded async concurrency.

An ``operator`` works on a whole ``stream``. A ``composer`` returns a
``stream``, while an ``aggregator`` reduces a ``stream`` to a non-stream result
that the wrapper emits as one or more ``items``. Some ``operators`` support both
behaviors depending on options, so use ``supported_subtypes`` metadata when
classification matters.

A ``splitter`` returns multiple ``streams``. The built-in ``split`` module
eagerly materializes its ``source`` before creating copies.

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
https     https://github.com/reubano/feed
file      file:///Users/reubano/Downloads/feed.xml
========  =========================================

Use ``riko.get_path()`` only for package data and repository examples. It is not
a general application data directory.

Which optional dependencies are available?
------------------------------------------

=========  ================================  ======================================
Extra      Packages                          Capability
=========  ================================  ======================================
``async``  AnyIO, httpx                      Asynchronous execution and HTTP paths
``perf``   fastfeedparser, ijson, lxml       Accelerated / streaming parser paths
finance    csv2ofx                           OFX and QIF export targets
=========  ================================  ======================================

From a checkout, install an ``extra`` with a quoted command such as
``pip install "riko[async]"``. Use ``list_targets()`` to discover the export
targets available in the active environment.

How do synchronous and asynchronous pipelines differ?
-----------------------------------------------------

``SyncPipe`` implements ordinary iteration. ``AsyncPipe`` implements async
iteration and can also be awaited. Awaiting materializes all remaining
``items``; ``async for`` preserves item-by-item consumption.

Fully consumed sync and async pipelines are tested for equivalent data output.
Execution mechanics can differ under partial consumption: an async mapping stage
may begin work for ``items`` that a downstream consumer never yields. Keep side
effects out of partially consumed mapping stages or bound work at the stage.

``SyncCollection`` fetches multiple configured sources sequentially or with a
local pool. ``AsyncCollection`` fetches sources concurrently with bounded
in-flight work.

What does ``parallel=True`` do?
-------------------------------

For ``SyncPipe``, eligible item-processing stages use a local thread pool by
default. Pass ``threads=False`` to use a process pool. The current sync mapping
path materializes the stage ``source`` before dispatch, so it is suitable only
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

    >>> from riko import SyncPipe
    >>>
    >>> flow = SyncPipe('hash', source=[{'content': 'a'}])
    >>> len(list(flow))
    1
    >>> list(flow)
    []

Build a new pipeline instance to rerun the workflow. Chaining after partial
consumption wraps the remaining ``source``. Chaining after ``close()`` or
failure raises ``PipelineStateError``.

Which operations materialize or retain input?
---------------------------------------------

Don't assume every ``pipe`` is fully streaming. Plan for full or partial
materialization when using:

- ``sort``, ``reverse``, and ``tail``;
- ``split``;
- aggregators such as ``count``, ``sum``, and ``join``;
- ``export()`` or serialized exports;
- awaiting an ``AsyncPipe``; or
- sync pool mapping with ``parallel=True``.

``AsyncPipe(parallel=True)`` uses bounded concurrency instead of materializing
an entire ``source``, but it still keeps in-flight and optionally prefetched
work. See the `Cookbook`_'s performance and memory section for practical guidance.

How do I send one stream to multiple consumers?
-----------------------------------------------

Use ``split`` for the simplest finite-stream copy. It eagerly materializes the
entire ``source`` and returns identical iterators.

Use ``send`` and ``receive`` for lazy in-process fan-out. Receivers must be
created and primed before the sender is consumed. Consuming the main sender
drives delivery to each named channel. This is an in-process coordination
mechanism, not an external message broker.

The `Cookbook`_ and the `README`_'s fan-out section include complete recipes for
both approaches.

Can I define a workflow as JSON?
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

What execution modes are available for compiled workflows?
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
it. See `Inspecting a workflow`_ in the cookbook for additional details.

The chainable classes share one pipeline model across four execution styles.

+------------------------------+----------------------------------------+------------------------------------------------+
| API / mode                   | How it runs                            | Important behavior                             |
+==============================+========================================+================================================+
| ``SyncPipe``                 | inline iterator pipeline               | single-use; lazy except sort / aggregate       |
+------------------------------+----------------------------------------+------------------------------------------------+
| ``SyncPipe(parallel=True)``  | local thread (or process) pool         | eligible stages; source materialized first     |
+------------------------------+----------------------------------------+------------------------------------------------+
| ``AsyncPipe``                | async iteration or ``await``           | await materializes; mapping may run eager      |
+------------------------------+----------------------------------------+------------------------------------------------+
| ``AsyncPipe(parallel=True)`` | bounded async concurrency              | tune ``connections`` / ``prefetch`` / ``order``|
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

The current public extension API doesn't include a runtime registration
function. ``list_modules()`` discovers packaged built-ins under
``riko.modules``; don't assume that an arbitrary decorated function becomes a
chainable named module automatically.

The `Cookbook`_ contains custom ``processor`` and ``operator`` examples, and the
`contributing guide`_ explains the additional work required for a built-in
module.

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
.. _What file types are supported: #what-file-types-are-supported
.. _What protocols are supported: #what-protocols-are-supported
.. _Which optional dependencies are available: #which-optional-dependencies-are-available
.. _How do synchronous and asynchronous pipelines differ: #how-do-synchronous-and-asynchronous-pipelines-differ
.. _What does parallel=True do: #what-does-paralleltrue-do
.. _Is riko distributed: #is-riko-distributed
.. _Why does a pipeline return no items the second time: #why-does-a-pipeline-return-no-items-the-second-time
.. _Which operations materialize or retain input: #which-operations-materialize-or-retain-input
.. _How do I send one stream to multiple consumers: #how-do-i-send-one-stream-to-multiple-consumers
.. _Can I define a workflow as JSON: #can-i-define-a-workflow-as-json
.. _What execution modes are available for compiled workflows: #what-execution-modes-are-available-for-compiled-workflows
.. _Can I create custom modules: #can-i-create-custom-modules
.. _How should errors and resource cleanup be handled: #how-should-errors-and-resource-cleanup-be-handled
.. _Where should I report problems or contribute: #where-should-i-report-problems-or-contribute
.. _Inspecting a workflow: https://github.com/nerevu/riko/blob/master/docs/COOKBOOK.rst#inspecting-a-workflow

.. _README: ../README.rst
.. _Cookbook: COOKBOOK.rst
.. _installation guide: INSTALLATION.rst
.. _contributing guide: ../CONTRIBUTING.rst
.. _issue tracker: https://github.com/nerevu/riko/issues
.. _DAG format: https://github.com/nerevu/riko/blob/master/docs/DAG_FORMAT.md
.. _Design Principles: https://github.com/nerevu/riko/blob/master/README.rst#design-principles
.. _Alternate workflow creation: https://github.com/nerevu/riko/blob/master/docs/COOKBOOK.rst#alternate-workflow-creation

.. _aggregate: https://github.com/nerevu/riko/blob/master/riko/modules/aggregate.py
.. _count: https://github.com/nerevu/riko/blob/master/riko/modules/count.py
.. _csv: https://github.com/nerevu/riko/blob/master/riko/modules/csv.py
.. _currencyformat: https://github.com/nerevu/riko/blob/master/riko/modules/currencyformat.py
.. _datebuilder: https://github.com/nerevu/riko/blob/master/riko/modules/datebuilder.py
.. _dateformat: https://github.com/nerevu/riko/blob/master/riko/modules/dateformat.py
.. _exchangerate: https://github.com/nerevu/riko/blob/master/riko/modules/exchangerate.py
.. _feedautodiscovery: https://github.com/nerevu/riko/blob/master/riko/modules/feedautodiscovery.py
.. _fetch: https://github.com/nerevu/riko/blob/master/riko/modules/fetch.py
.. _fetchdata: https://github.com/nerevu/riko/blob/master/riko/modules/fetchdata.py
.. _fetchpage: https://github.com/nerevu/riko/blob/master/riko/modules/fetchpage.py
.. _fetchsitefeed: https://github.com/nerevu/riko/blob/master/riko/modules/fetchsitefeed.py
.. _fetchtable: https://github.com/nerevu/riko/blob/master/riko/modules/fetchtable.py
.. _fetchtext: https://github.com/nerevu/riko/blob/master/riko/modules/fetchtext.py
.. _filter: https://github.com/nerevu/riko/blob/master/riko/modules/filter.py
.. _forever: https://github.com/nerevu/riko/blob/master/riko/modules/forever.py
.. _geolocate: https://github.com/nerevu/riko/blob/master/riko/modules/geolocate.py
.. _hash: https://github.com/nerevu/riko/blob/master/riko/modules/hash.py
.. _input: https://github.com/nerevu/riko/blob/master/riko/modules/input.py
.. _itembuilder: https://github.com/nerevu/riko/blob/master/riko/modules/itembuilder.py
.. _join: https://github.com/nerevu/riko/blob/master/riko/modules/join.py
.. _loop: https://github.com/nerevu/riko/blob/master/riko/modules/loop.py
.. _receive: https://github.com/nerevu/riko/blob/master/riko/modules/receive.py
.. _refind: https://github.com/nerevu/riko/blob/master/riko/modules/refind.py
.. _regex: https://github.com/nerevu/riko/blob/master/riko/modules/regex.py
.. _rename: https://github.com/nerevu/riko/blob/master/riko/modules/rename.py
.. _reverse: https://github.com/nerevu/riko/blob/master/riko/modules/reverse.py
.. _rssitembuilder: https://github.com/nerevu/riko/blob/master/riko/modules/rssitembuilder.py
.. _send: https://github.com/nerevu/riko/blob/master/riko/modules/send.py
.. _simplemath: https://github.com/nerevu/riko/blob/master/riko/modules/simplemath.py
.. _slugify: https://github.com/nerevu/riko/blob/master/riko/modules/slugify.py
.. _sort: https://github.com/nerevu/riko/blob/master/riko/modules/sort.py
.. _split: https://github.com/nerevu/riko/blob/master/riko/modules/split.py
.. _strconcat: https://github.com/nerevu/riko/blob/master/riko/modules/strconcat.py
.. _strfind: https://github.com/nerevu/riko/blob/master/riko/modules/strfind.py
.. _strreplace: https://github.com/nerevu/riko/blob/master/riko/modules/strreplace.py
.. _strtransform: https://github.com/nerevu/riko/blob/master/riko/modules/strtransform.py
.. _subelement: https://github.com/nerevu/riko/blob/master/riko/modules/subelement.py
.. _substr: https://github.com/nerevu/riko/blob/master/riko/modules/substr.py
.. _sum: https://github.com/nerevu/riko/blob/master/riko/modules/sum.py
.. _tail: https://github.com/nerevu/riko/blob/master/riko/modules/tail.py
.. _timeout: https://github.com/nerevu/riko/blob/master/riko/modules/timeout.py
.. _tokenizer: https://github.com/nerevu/riko/blob/master/riko/modules/tokenizer.py
.. _truncate: https://github.com/nerevu/riko/blob/master/riko/modules/truncate.py
.. _typecast: https://github.com/nerevu/riko/blob/master/riko/modules/typecast.py
.. _udf: https://github.com/nerevu/riko/blob/master/riko/modules/udf.py
.. _union: https://github.com/nerevu/riko/blob/master/riko/modules/union.py
.. _uniq: https://github.com/nerevu/riko/blob/master/riko/modules/uniq.py
.. _urlbuilder: https://github.com/nerevu/riko/blob/master/riko/modules/urlbuilder.py
.. _urlparse: https://github.com/nerevu/riko/blob/master/riko/modules/urlparse.py
.. _xpathfetchpage: https://github.com/nerevu/riko/blob/master/riko/modules/xpathfetchpage.py
