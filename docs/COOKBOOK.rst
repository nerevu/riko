riko Cookbook
=============

This cookbook presents ``riko`` recipes from basic iterator pipelines through
asynchronous execution, custom modules, testing, and compiling workflow documents.
Examples that read files use data bundled with ``riko`` (via ``get_path``) so
they run offline.

.. contents::
   :local:
   :depth: 2

Beginner recipes
----------------

Build your first pipeline
^^^^^^^^^^^^^^^^^^^^^^^^^

Create one ``item``, tokenize its ``content`` field into three ``items``, and
count them.

.. code-block:: python

    >>> from riko import Pipeline, Sources
    >>>
    >>> conf = {'attrs': {'key': 'content', 'value': 'a,bb,ccc'}}
    >>> pipeline = (
    ...     Pipeline.from_module(Sources.ITEMBUILDER, conf=conf)
    ...     .tokenizer(options={'emit': True})
    ...     .count()
    ... )
    >>> pipeline.first()
    {'count': 3}

``Pipeline`` resolves each chained attribute as a built-in ``module``. A module name
can be either a string or (as shown above) a member of the typed discovery tree
(``Sources``/``Transforms``/``Sinks``). The ``pipeline`` is an immutable definition, so
it does no work until it is iterated (e.g., by ``list()``, a ``for`` loop,
``.first()``, or an export). See `discovering modules`_ in the FAQ for
``list_modules`` and ``describe_module``.

Transform, filter, and order items
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The next ``pipeline`` keeps scores greater than 10, creates a slug from each title,
and orders the items by score.

.. code-block:: python

    >>> from riko import Pipeline
    >>>
    >>> items = [
    ...     {'title': 'Draft report', 'score': 8},
    ...     {'title': 'Final report', 'score': 21},
    ...     {'title': 'Release notes', 'score': 13},
    ... ]
    >>> rule = {'field': 'score', 'op': 'greater', 'value': 10}
    >>> replace = {'rule': {'find': ' ', 'replace': '-'}}
    >>> pipeline = (
    ...     Pipeline(source=items)
    ...         .filter(conf={'rule': rule})
    ...         .strreplace(conf=replace, options={'field': 'title', 'assign': 'slug'})
    ...         .sort(conf={'rule': {'field': 'score'}})
    ... )
    >>> [(item['slug'], item['score']) for item in pipeline]
    [('Release-notes', 13), ('Final-report', 21)]

Call options travel in ``options``. ``field`` selects the input field passed to a
``processor``. ``assign`` names the field receiving the result. Passing
``options={'emit': True}`` instead yields the processed value as a new ``item`` rather than
assigning it to the original.

Combine multiple rules
^^^^^^^^^^^^^^^^^^^^^^

``filter`` accepts one rule or a list of rules. ``combine`` is ``and`` by
default and can be set to ``or``.

.. code-block:: python

    >>> from riko import Pipeline
    >>>
    >>> items = [
    ...     {'title': 'Alpha', 'score': 5, 'published': True},
    ...     {'title': 'Beta', 'score': 15, 'published': False},
    ...     {'title': 'Gamma', 'score': 20, 'published': True},
    ... ]
    >>> rules = [
    ...     {'field': 'score', 'op': 'atleast', 'value': 10},
    ...     {'field': 'published', 'op': 'truthy'},
    ... ]
    >>> pipeline = Pipeline(source=items).filter(conf={'rule': rules})
    >>> [item['title'] for item in pipeline]
    ['Gamma']

Set ``permit=False`` to exclude matches instead of keeping them.

Read structured data
^^^^^^^^^^^^^^^^^^^^

``get_path`` resolves files bundled in ``riko/data`` and makes documentation
examples deterministic.

.. code-block:: python

    >>> from riko import Pipeline, Sources, get_path
    >>>
    >>> pipeline = Pipeline.from_module(Sources.FETCHDATA, conf={'url': get_path('quote.json')})
    >>> pipeline.first()['base']
    'USD'

Use ``fetchdata`` for JSON or XML records, ``csv`` for CSV parsing, and
``fetchtable`` for supported tabular formats. See the `FAQ`_ for the full format
matrix and each ``module`` configuration.

Read feeds
^^^^^^^^^^

``fetch`` normalizes RSS or Atom entries into dictionary-like ``items``.

.. code-block:: python

    >>> from riko import Pipeline, Sources, get_path
    >>>
    >>> pipeline = Pipeline.from_module(Sources.FETCH, conf={'url': get_path('feed.xml')})
    >>> item = pipeline.first()
    >>> {'author', 'content', 'id', 'link', 'published', 'summary', 'title'} <= set(item)
    True
    >>> item['title']
    'Donations'

Use ``fetchsitefeed`` to fetch the first feed discovered on a page or
``feedautodiscovery`` to return feed links for separate processing.

Read unstructured web content
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``fetchpage`` returns page content and can select text between delimiters and
strip markup. This example uses an offline HTML fixture.

.. code-block:: python

    >>> from riko import Pipeline, Sources, get_path
    >>>
    >>> pipeline = (
    ...     Pipeline.from_module(
    ...         Sources.FETCHPAGE,
    ...         conf={
    ...             'url': get_path('users.jyu.fi.html'),
    ...             'start': '<body>',
    ...             'end': '</body>',
    ...             'detag': True})
    ...         .strreplace(
    ...             conf={'rule': {'find': '\n', 'replace': ' '}},
    ...             options={'assign': 'content'})
    ...         .tokenizer(conf={'delimiter': ' '}, options={'emit': True})
    ...         .count()
    ... )
    >>> list(pipeline)
    [{'count': 70}]

Use ``fetchtext`` for plain text files and ``xpathfetchpage`` when XPath-based
selection is required and its optional XML parser (``lxml``) is installed.

User input
^^^^^^^^^^

Some ``pipelines`` require user input (via the ``input`` module). By default,
``input`` prompts the user via the console, but in some situations this may not
be appropriate, e.g., testing or integrating with a website. In such cases, set
``test`` in the ``conf`` so the module uses its ``default`` instead of prompting.

.. code-block:: python

    >>> from riko import Pipeline, Sources
    >>>
    >>> conf = {'prompt': 'How old are you?', 'type': 'int', 'default': '30', 'test': True}
    >>> Pipeline.from_module(Sources.INPUT, conf=conf).first()
    30

Intermediate recipes
--------------------

Fetching data and feeds
^^^^^^^^^^^^^^^^^^^^^^^

``riko`` can read both local and remote filepaths via ``source`` modules. All ``source``
modules return a ``pipeline``. Use ``iter`` to obtain a ``stream`` iterator of
dictionaries, aka ``items``.

.. code-block:: python

    >>> from riko import Pipeline, Sources, parse_dag, get_path
    >>>
    >>> # Note: `get_path` looks up a cached copy of a URL in the `data`
    >>> # directory, so these examples run offline
    >>>
    >>> ### Fetch a web page ###
    >>> pipeline = Pipeline.from_module(Sources.FETCHPAGE, conf={'url': get_path('users.jyu.fi.html')})
    >>>
    >>> ### Fetch a data file ###
    >>> pipeline = Pipeline.from_module(Sources.FETCHDATA, conf={'url': get_path('quote.json')})
    >>>
    >>> ### View the fetched data ###
    >>> stream = iter(pipeline)
    >>> item = next(stream)
    >>> item['base']
    'USD'
    >>> ### Fetch an RSS feed ###
    >>> pipeline = Pipeline.from_module(Sources.FETCH, conf={'url': get_path('feed.xml')})
    >>>
    >>> ### Fetch the first RSS feed found on a page ###
    >>> pipeline = Pipeline.from_module(Sources.FETCHSITEFEED, conf={'url': get_path('cnn.html')})
    >>>
    >>> ### Find all RSS links on a page and fetch the feeds ###
    >>> pipeline = Pipeline.from_module(Sources.FEEDAUTODISCOVERY, conf={'url': get_path('bbc.html')})
    >>> urls = [entry['link'] for entry in pipeline]
    >>> urls
    ['file://riko/data/bbci.co.uk.xml']
    >>> pipeline = Pipeline.from_module(Sources.FETCH, conf={'url': urls[0]})
    >>>
    >>> ### Alternatively, fetch every discovered feed in one workflow ###
    >>> #
    >>> # A `union` node merges any number of `fetch` nodes wired into it, so
    >>> # several sources become a single stream (wires, ports, and `parse_dag`
    >>> # are explained under "Fetch several sources" below)
    >>> modules = [
    ...     {'id': f'feed-{n}', 'name': 'fetch', 'conf': {'url': url}}
    ...     for n, url in enumerate(urls)
    ... ]
    >>> wires = [
    ...     [f'feed-{n}', 'merged', f'in:{n}' if n else 'in']
    ...     for n in range(len(urls))
    ... ]
    >>> modules.append({'id': 'merged', 'name': 'union', 'conf': {}})
    >>> pipeline = Pipeline(parse_dag({'modules': modules, 'wires': wires}))
    >>>
    >>> ### View the fetched RSS feed(s) ###
    >>> #
    >>> # Note: regardless of how you fetch an RSS feed, it will have the same
    >>> # structure
    >>> pipeline.first()['title']
    "EU sets out 'phased' Brexit strategy"

Alternate ``conf`` value entry
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A ``conf`` value doesn't have to be a literal. A ``subkey`` reference reads a field of
the current ``item``, and a terminal reference (below) reads the next item from another
node's stream.

.. code-block:: python

    >>> from riko import Pipeline, Sources, get_path
    >>>
    >>> conf = {'url': {'subkey': 'url'}}
    >>> items = [{'url': get_path('feed.xml')}]
    >>> pipeline = items | Pipeline.from_module(Sources.FETCH, conf=conf)
    >>> item = pipeline.first()
    >>> {'author', 'content', 'id', 'link', 'published', 'summary', 'title'} <= set(item)
    True

A ``conf`` value can also come from another node in a workflow. Declare the value
as a terminal reference, and wire the producing node into a port with the same name as
the terminal with an ``in:`` prefix (a name starting with a digit gets a leading underscore,
so ``1_URL`` becomes ``in:_1_URL``).

Here ``urlbuilder`` produces the URL that ``fetch`` reads. `Fetch several sources`_
introduces wires and ports, and `Compiling workflow documents`_ covers ``parse_dag``.
The `DAG format doc`_ has the full rules for conf values filled from another node.

.. code-block:: python

    >>> from riko import Pipeline, parse_dag, get_path
    >>>
    >>> base = get_path('feed.xml')
    >>> fetch_conf = {'url': {'terminal': '1_URL', 'type': 'url'}}
    >>>
    >>> dag = {
    ...     'modules': [
    ...         {'id': 'url', 'name': 'urlbuilder', 'conf': {'base': base}},
    ...         {'id': 'feed', 'name': 'fetch', 'conf': fetch_conf},
    ...     ],
    ...     'wires': [['url', 'feed', 'in:_1_URL']],
    ... }
    >>> Pipeline(parse_dag(dag)).first()['title']
    'Donations'

Alternate pipeline creation
^^^^^^^^^^^^^^^^^^^^^^^^^^^

In addition to `Pipeline chaining`_ ``riko`` supports a pure functional
style [#]_. Every built-in module's ``pipe`` can also be called directly, which is useful
when control flow is easier to express explicitly.

.. warning::

   Direct module imports are implementation-level APIs and are not covered by
   the stable API guarantee. Application code that needs the stable public surface
   should prefer ``Pipeline``.

.. code-block:: python

    >>> from riko import get_path
    >>> from riko.modules.fetchpage import pipe as fetchpage
    >>> from riko.modules.strreplace import pipe as strreplace
    >>> from riko.modules.tokenizer import pipe as tokenizer
    >>> from riko.modules.count import pipe as count
    >>>
    >>> ### Set the module configurations ###
    >>> #
    >>> # Notes:
    >>> #   - `get_path` just looks up files in the `data` directory to simplify
    >>> #      testing
    >>> #   - the `detag` option will strip all html tags from the result
    >>> url = get_path('users.jyu.fi.html')
    >>> fetch_conf = {'url': url, 'start': '<body>', 'end': '</body>', 'detag': True}
    >>> replace_conf = {'rule': {'find': '\n', 'replace': ' '}}
    >>>
    >>> ### Create a pipeline ###
    >>> #
    >>> # The following pipeline will:
    >>> #   1. fetch the URL and return the content between the body tags
    >>> #   2. replace newlines with spaces
    >>> #   3. tokenize (split) the content by spaces, i.e., yield words
    >>> #   4. count the words
    >>> #
    >>> pages = fetchpage(conf=fetch_conf)
    >>> replaced = strreplace(pages, conf=replace_conf, assign='content')
    >>> words = tokenizer(replaced, conf={'delimiter': ' '}, emit=True)
    >>> counts = count(words)
    >>> next(counts)
    {'count': 70}

Notes

.. [#] See `Design Principles`_ for explanation on module types and sub-types

Chaining with the ``|`` operator or ``pipe`` method
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Alongside attribute chaining (``pipeline.tokenizer(...)``), a ``node`` can be added to the
``pipeline`` with the ``|`` operator or the ``pipe`` method. These take the module name
as either a string or a typed ``Sources``/``Transforms``/``Sinks`` member. They also
accept dynamic or dotted name modules, e.g., ``"microsoft.autopilot.ensure"``, and a
single-module ``Pipeline`` used as a reusable template.

.. code-block:: python

    >>> from riko import Pipeline, Transforms
    >>>
    >>> src = [{"content": "a,b,c,a"}]
    >>>
    >>> # seed a pipeline with ``items | pipeline``
    >>> pipeline = src | Pipeline.from_module(Transforms.TOKENIZER)
    >>> pipeline.first()
    {'content': 'a'}
    >>>
    >>> # chain a module by name
    >>> (pipeline | Transforms.HASH).first()
    {'content': 'a', 'hash': 1267964084}
    >>>
    >>> # chain a module by ``(name, conf)`` pair
    >>> list(pipeline | (Transforms.TRUNCATE, {"count": 2}))
    [{'content': 'a'}, {'content': 'b'}]
    >>>
    >>> # chain with a dynamic module name
    >>> module = "count"
    >>> pipeline.pipe(module).first()
    {'count': 4}
    >>>
    >>> # chain a single-module template
    >>> counter = Pipeline.from_module(Transforms.COUNT)
    >>> (pipeline | counter).first()
    {'count': 4}

Fetch several sources
^^^^^^^^^^^^^^^^^^^^^

A ``union`` node merges ``items`` from multiple ``source`` nodes. Build the fan-in
with ``parse_dag``: each wire names the ``union`` port it enters, so the first
source goes to ``in`` and the rest to ``in:1``, ``in:2``, and so on (see the
`DAG format doc`_).

.. code-block:: python

    >>> from riko import Pipeline, parse_dag, get_path
    >>>
    >>> dag = {
    ...     'modules': [
    ...         {'id': 'first', 'name': 'fetch', 'conf': {'url': get_path('feed.xml')}},
    ...         {'id': 'second', 'name': 'fetch', 'conf': {'url': get_path('gawker.xml')}},
    ...         {'id': 'merged', 'name': 'union', 'conf': {}},
    ...     ],
    ...     'wires': [['first', 'merged'], ['second', 'merged', 'in:1']],
    ... }
    >>> feeds = Pipeline(parse_dag(dag))
    >>> len(list(feeds))
    32

Concurrency is an execution-wide setting rather than a property of a node. It is
declared on the ``Pipeline`` with ``with_execution``. It applies to the item-wise
``processor`` steps, such as ``fetch``.

.. code-block:: python

    >>> concurrent = feeds.with_execution(executor="thread", concurrency=4)
    >>> len(list(concurrent))
    32

.. note::

   Pending. The branches feeding a fan-in such as ``union`` are still pulled one at
   a time. Pulling them concurrently is not available yet.

Managing pipeline lifecycle
^^^^^^^^^^^^^^^^^^^^^^^^^^^

A ``Pipeline`` is an immutable *definition*, not a running stream. Each iteration starts
a fresh one-shot run, so iterating twice runs the ``pipeline`` twice. There is no run
state to inspect or reset.

.. code-block:: python

    >>> from riko import Pipeline
    >>>
    >>> pipeline = Pipeline(source=[{'content': 'a'}, {'content': 'b'}]).hash()
    >>> len(list(pipeline))                    # one execution
    2
    >>> len(list(pipeline))                    # a fresh execution, same result
    2

Closing an iterator early tears that execution down and releases whatever it
acquired; the definition is unaffected.

.. code-block:: python

    >>> stream = iter(pipeline)
    >>> next(stream)['content']
    'a'
    >>> stream.close()
    >>> len(list(pipeline))
    2

Chaining derives a *new* definition and leaves the original untouched. A
``pipeline`` can serve as the prefix of several ``pipelines``.

.. code-block:: python

    >>> counted = pipeline.count()
    >>> sorted(pipeline.workflow.nodes), sorted(counted.workflow.nodes)
    (['hash-1'], ['count-1', 'hash-1'])
    >>> list(counted)
    [{'count': 2}]

Exporting a stream
^^^^^^^^^^^^^^^^^^

Iterating a ``pipeline`` yields ``items`` one at a time. ``export()`` materializes
them into a concrete list you can index, measure, and reuse.

.. code-block:: python

    >>> from riko import Pipeline, export
    >>>
    >>> pipeline = Pipeline(source=[{'title': 'a'}, {'title': 'b'}]).hash()
    >>> items = export(pipeline)
    >>> len(items), items[0]['title']      # unlike the pipeline, indexable & measurable
    (2, 'a')

You can pass an export type as the second argument ``list`` (the default) and ``tuple``
return the items, and a format serializes them. A format may be a plain string or a
member of the typed ``Formats`` enum (recommended, for editor autocompletion).
``list_formats()`` lists the formats available at runtime (``ofx``/``qif`` require the
optional ``csv2ofx`` dependency). A format returns a ``StringIO`` buffer.

.. code-block:: python

    >>> from riko import Formats, list_formats
    >>>
    >>> source = [{"title": "a"}, {"title": "b"}]
    >>> pipeline = Pipeline(source=source).hash(options={"field": "title"})
    >>> {"csv", "geojson", "json", "jsonl"}.issubset(list_formats())
    True
    >>> export(pipeline, "tuple")
    ({'title': 'a', 'hash': 1267964084}, {'title': 'b', 'hash': 2297772648})
    >>> export(pipeline, Formats.JSON).getvalue()
    '[{"hash": 1267964084, "title": "a"}, {"hash": 2297772648, "title": "b"}]'


For serialized output, you can pass a file path or file like object as the third
argument.

``export()`` consumes the whole stream. To write **inside** a pipeline uninterrupted,
chain the ``write`` module: it serializes the stream to file with a ``Formats``
converter (``fmt`` defaults to the ``dest`` extension) and passes every item through
unchanged. This allows you to persist an intermediate result and continue processing.

.. code-block:: python

    >>> from riko import Pipeline, Sources, get_temp_file
    >>>
    >>> conf = {"attrs": {"key": "content", "value": "a,bb,ccc"}}
    >>> with get_temp_file() as fp:
    ...     pipeline = (
    ...         Pipeline.from_module(Sources.ITEMBUILDER, conf=conf)
    ...         .tokenizer()
    ...         .write(conf={"dest": fp.name})
    ...         .count()
    ...     )
    ...     pipeline.first()
    ...     fp.read()
    {'count': 3}
    b'[{"content": "a"}, {"content": "bb"}, {"content": "ccc"}]'

Given a destination directly, ``write`` instead appends a *write node* that declares
where the items go, how they are serialized, and how they reconcile with what is
already there.

.. code-block:: python

    pipeline = (
        Pipeline.from_module(Sources.ITEMBUILDER, conf=conf)
        .tokenizer()
        .write("report.csv", mode="replace")
        .count()
    )

.. note::

   Pending. ``pipeline.write(path, mode=, fmt=, keys=)`` already appends the write node
   to the definition, but iterating the pipeline raises ``InvalidPipelineError``
   until write-node execution lands. Use ``write(conf={"dest": ...})`` to write
   from inside a pipeline today.

Note that ``export`` is **eager**: it serializes the complete input stream into
memory, so don't use it on an unbounded ``stream``. The ``write`` module is likewise
eager: it serializes the whole ``stream`` before writing it.

Asynchronous pipelines
----------------------

The ``async`` extra (``python -m pip install "riko[async]"``) lets the same
``Pipeline`` run asynchronously. Build a ``pipeline`` the same way, then consume it
with ``async for`` (or ``anext`` on ``aiter(pipeline)``). ``riko.run(main)`` runs an
async function on the installed backend.

Each async ``source`` fetch reads its body fully into memory before parsing (a
single ``await``). So ``stream`` here means ``Iterator[item]``, not an incremental
network read.

Lazy async iteration
^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    >>> from riko import Pipeline, Sources, get_path, run
    >>>
    >>> fetch_conf = {'url': get_path('feed.xml')}
    >>> filter_rule = {'field': 'title', 'op': 'contains', 'value': 'a'}
    >>>
    >>> ### Consume a Pipeline item-by-item with `async for` ###
    >>> async def main():
    ...     pipeline = (
    ...         Pipeline.from_module(Sources.FETCH, conf=fetch_conf)
    ...         .filter(conf={'rule': filter_rule})
    ...     )
    ...     titles = [item['title'] async for item in pipeline]
    ...     print(titles[0], '/', len(titles))
    >>>
    >>> run(main)
    Donations / 5

To take just the first ``item``, close the async iterator afterwards so the
execution it started is torn down.

.. code-block:: python

    >>> async def first():
    ...     stream = aiter(Pipeline.from_module(Sources.FETCH, conf=fetch_conf))
    ...     item = await anext(stream)
    ...     await stream.aclose()
    ...     print(item['title'])
    >>>
    >>> run(first)
    Donations

Fetching feeds asynchronously
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The ``union`` fan-in ``dag`` from `Fetch several sources`_ runs unchanged under
``async for``. Each ``fetch`` node is awaited on the async backend and their output
streams merge into a single ``stream``. As under ``for``, the branches are pulled one at a
time. Pulling them concurrently is not available yet.

.. code-block:: python

    >>> from riko import Pipeline, parse_dag, get_path, run
    >>>
    >>> async def main():
    ...     dag = {
    ...         'modules': [
    ...             {'id': 'first', 'name': 'fetch', 'conf': {'url': get_path('feed.xml')}},
    ...             {'id': 'second', 'name': 'fetch', 'conf': {'url': get_path('gawker.xml')}},
    ...             {'id': 'merged', 'name': 'union', 'conf': {}},
    ...         ],
    ...         'wires': [['first', 'merged'], ['second', 'merged', 'in:1']],
    ...     }
    ...     feeds = Pipeline(parse_dag(dag))
    ...     print(len([item async for item in feeds]))
    >>>
    >>> run(main)
    32

Bounded parallelism
^^^^^^^^^^^^^^^^^^^

Bounded ``concurrency`` with backpressure is an execution-wide setting declared with
``with_execution``. It caps the number of in-flight ``items`` across the whole run,
and ``ordered`` determines whether items keep source order. By default, items
arrive as they complete. Here ``hash`` processes each token the ``tokenizer`` emits,
at most two at a time, in source order.

.. code-block:: python

    >>> from riko import Pipeline, Sources, run
    >>>
    >>> async def main():
    ...     conf = {'attrs': {'key': 'content', 'value': 'a,bb,ccc'}}
    ...     pipeline = (
    ...         Pipeline.from_module(Sources.ITEMBUILDER, conf=conf)
    ...         .tokenizer(options={'emit': True})
    ...         .hash()
    ...         .with_execution(concurrency=2, ordered=True)
    ...     )
    ...     print([item['content'] async for item in pipeline])
    >>>
    >>> run(main)
    ['a', 'bb', 'ccc']

Under ``async for`` native async work runs inline and synchronous work runs on worker
threads (or on the event-loop thread with the inline executor). The ``source`` is
pulled only as workers free up. Under ``for`` a thread or process pool likewise pulls
the ``source`` no further ahead than it has workers.

Advanced recipes
----------------

Handling errors
^^^^^^^^^^^^^^^

Module and ``source`` exceptions propagate to the caller of the iteration that
hit them. Because a ``Pipeline`` is a definition rather than a running stream,
there is no failed state left behind: the error belongs to that one execution.

.. code-block:: python

    >>> from riko import Pipeline
    >>>
    >>> def broken_source():
    ...     yield {'content': 'first'}
    ...     raise RuntimeError('broken input')
    >>>
    >>> pipeline = Pipeline(source=broken_source()).hash()
    >>> try:
    ...     list(pipeline)
    ... except RuntimeError as exc:
    ...     print(exc)
    broken input

``riko`` doesn't provide a general retry policy or durable recovery layer. Put
retryable I/O behind a function or module with an explicit policy, or run
``riko`` inside an orchestrator when task-level retries and persistence are
required.

Using a one-off function
^^^^^^^^^^^^^^^^^^^^^^^^

The built-in ``udf`` ``processor`` applies a Python callable to each ``item``.
It is the simplest option when a transformation is local to one application.
A ``Pipeline`` holds only JSON-native values, so a callable cannot
travel through ``options``; call the ``pipe`` functionally instead.

.. code-block:: python

    >>> from riko.modules.udf import pipe as udf
    >>>
    >>> def add_length(item):
    ...     return {**item, 'length': len(item['content'])}
    >>>
    >>> items = [{'content': 'a'}, {'content': 'abcd'}]
    >>> [item['length'] for item in udf(items, func=add_length, emit=True)]
    [1, 4]

Inside a ``Pipeline`` chain, ``map`` will append the callable as its own node.

.. code-block:: python

    pipeline = Pipeline(source=items).map(add_length)
    [item['length'] for item in pipeline]

.. note::

   Pending. ``map`` exists on ``Pipeline`` but raises ``NotImplementedError``
   until callable nodes land.

Use the extension decorators when the transformation should have normal ``riko``
configuration, assignment, metadata, and sync/async wrappers.

Creating a custom processor
^^^^^^^^^^^^^^^^^^^^^^^^^^^

``processor`` wraps a function that handles one ``item`` at a time. A decorated
callable can be invoked functionally, or registered so ``Pipeline`` resolves it
by name (see `Registering a custom module`_ below).

.. code-block:: python

    >>> from riko.ext import processor
    >>>
    >>> @processor()
    ... def uppercase(item, extraction, objconf, **kwargs) -> str:
    ...     return str(item['content']).upper()
    >>>
    >>> next(uppercase({'content': 'hello'}, assign='content'))
    {'content': 'HELLO'}

A ``processor`` can return one value, an ``item``, or an iterator. Use ``field``
and ``assign`` at the call site to control extraction and assignment.

The async interface accepts a sync *or* async callable, so ``async_pipe`` may be a plain
``def`` that returns the sync parser (as built-in ``count``/``reverse``/``sort`` do)
*or* an ``async def`` that awaits real I/O (as ``strreplace``/``timeout`` and
`register_module.py`_ do). Pass ``isasync=True`` when you wrap a sync function for the
async interface. At runtime it is only required when the function isn't named
``async_pipe``, but a type checker needs it whenever you assign the result to a typed
``async_pipe`` slot (as `register_module.py`_ does).

Creating a custom operator
^^^^^^^^^^^^^^^^^^^^^^^^^^

``operator`` receives the whole ``stream``. Use it for selection, aggregation,
or composition that cannot be expressed as an item-level ``processor``.

.. code-block:: python

    >>> from riko.ext import operator
    >>>
    >>> @operator(emit=True)
    ... def every_other(stream, extraction, tuples, **kwargs):
    ...     return (item for index, item in enumerate(stream) if index % 2 == 0)
    >>>
    >>> items = [{'value': value} for value in range(5)]
    >>> [item['value'] for item in every_other(items)]
    [0, 2, 4]

``operator`` functions should preserve iterator behavior unless the operation
requires materialization. Add both sync and async wrappers when users need both
execution APIs.

Registering a custom module
^^^^^^^^^^^^^^^^^^^^^^^^^^^

To make a custom module resolvable by name, i.e., so
``Pipeline.from_module('your.module', ...)`` and the ``|`` operator find it, register
it with ``riko.ext.register_module`` or declare a ``[project.entry-points."riko.modules"]``
entry point. Point a ``ModuleDefinition`` at a module exposing ``pipe``/``async_pipe``,
or pass those callables explicitly. See `riko-example-ext`_ (installable extension
package), `register_module.py`_ (runtime ``register_module`` with explicit callables), and
`register_alias.py`_ (runtime ``register_module`` aliasing a built-in), plus the `FAQ`_ entry
`Can I create custom modules`_ for the mechanics.

Providing resources
^^^^^^^^^^^^^^^^^^^

A module can access ``resources`` (e.g., a database connection or HTTP session) from its
``Context``. Add one using ``pipeline.with_resource``. If you already have a ``Context``
with resources (from a ``context.with_resource``), pass it to the ``Pipeline`` with
``pipeline.with_context``.

.. code-block:: python

    >>> from riko import Context, Pipeline
    >>>
    >>> def open_db():
    ...     connection = {'rows': []}
    ...     yield connection
    >>>
    >>> pipeline = Pipeline.from_module('fetch').with_resource('db', open_db)
    >>> sorted(pipeline.context.resources)
    ['db']
    >>> context = Context(inputs={'limit': 5}).with_resource('db', open_db)
    >>> pipeline = Pipeline.from_module('fetch').with_context(context)
    >>> pipeline.context is context
    True

Fanning out a stream
^^^^^^^^^^^^^^^^^^^^

Sometimes you need to consume the same ``stream`` from multiple independent pipelines.
For example, archiving every item while also sending urgent items to an alert queue.
Consuming the iterator twice would exhaust it, and materialising it into a list defeats
lazy evaluation. ``publish`` and ``subscribe`` are planned for this: a subscription
will itself be a ``Pipeline`` declared with ``Pipeline.subscribe``, and ``publish``
will send a copy of each ``item`` into it while the main ``pipeline`` continues. The
subscription's ``func`` will see each ``item`` as it is published.

.. code-block:: python

    from riko import Pipeline

    items = [{'title': 'Gravity paper'}, {'title': 'Breaking: riko 4.0'}]
    received = []
    subscriber = Pipeline.subscribe('subscriber', func=received.append)
    publisher = Pipeline(source=items).publish(subscriber)

    ### Consuming the publisher drives the push ###
    _ = list(publisher)

    ### The subscriber saw every item as it was published ###
    [item['title'] for item in received]

.. note::

   Pending. ``Pipeline.subscribe`` and ``publish`` exist but raise
   ``NotImplementedError`` until local subscriptions and publishing land.

``publish`` is designed to compose in a ``Pipeline`` chain via ``.publish(...)``.
The ``stream`` will continue down the main ``pipeline`` while a copy flows to each
subscription. A subscription's ``func`` will run as each ``item`` is received; its
return value is discarded and the ``item`` passes through unchanged. ``isolate`` will
keep a subscriber's failures out of the main ``pipeline``:

.. code-block:: python

    from riko import Pipeline

    ### `archived` and `alerted` stand in for your real side effects ###
    archived, alerted = [], []
    everything = Pipeline.subscribe('everything', func=archived.append)
    breaking = Pipeline.subscribe('breaking', func=alerted.append)

    items = [
        {'title': 'quiet', 'score': 42},
        {'title': 'breaking: riko 4.0', 'score': 980},
        {'title': 'also big', 'score': 750}
    ]

    ### Send ALL items to 'everything', filter, then send matches to 'breaking' ###
    pipeline = (
        Pipeline(source=items)
            .publish(everything)
            .filter(conf={'rule': [{'field': 'score', 'value': 500, 'op': 'greater'}]})
            .publish(breaking, isolate=True)
            .sort(conf={'rule': [{'field': 'score'}]})
    )

    ### Consume the main pipeline (this also drives the pushes) ###
    [item['title'] for item in pipeline]  # sorted high score items

.. note::

   Pending. The chained form raises ``NotImplementedError`` like the standalone
   one until local subscriptions and publishing land.

A subscription is not a replay buffer. It sees ``items`` only while a publisher runs.
Iterating a subscription on its own afterwards starts a fresh, empty run. Observe
published ``items`` through ``func`` (or a write inside the subscription), not by
draining the subscription later.

``split`` vs ``publish``/``subscribe``
''''''''''''''''''''''''''''''''''''''

``split`` is the other planned way to fan a ``stream`` out. It will return one
``Pipeline`` per branch:

.. code-block:: python

    from riko import Pipeline

    items = [{'title': 'riko pt. 1'}, {'title': 'riko pt. 2'}]
    left, right = Pipeline(source=items).split(2)
    left.first(), right.first()

.. note::

   Pending. ``split`` exists on ``Pipeline`` but raises ``NotImplementedError``
   until streaming fan-out lands.

The planned difference between them is the shape of the API. ``split`` will return
every branch at once, and each branch will be an identical copy of the ``stream``.
``publish``/``subscribe`` will name each branch up front, let it carry its own
per-item callback, and let the main ``pipeline`` keep flowing while each subscriber
handles the ``items`` published to it.

+-------------------------------+---------------------------+----------------------------+
| Dimension                     | ``split``                 | ``publish`` / ``subscribe``|
+===============================+===========================+============================+
| API                           | Returns N pipelines       | Subscribers handle items   |
|                               | in one call               | as they are published      |
+-------------------------------+---------------------------+----------------------------+
| Callback per branch           | No. Identical copies.     | Yes. ``func=`` in each     |
|                               |                           | ``subscribe``; its return  |
|                               |                           | value is discarded         |
+-------------------------------+---------------------------+----------------------------+
| ``Pipeline`` chain            | ``split(2)`` ends the     | ``.publish(...)`` stays in |
|                               | chain with N branches     | the chain                  |
+-------------------------------+---------------------------+----------------------------+

Once they land, ``split`` will suit branches that all need the same ``items`` through
the simplest possible API. ``publish``/``subscribe`` will suit branches that should
run independently, or a main ``pipeline`` that must stay in the chain (e.g., inside a
``timeout`` or ``truncate`` composer). ``subscribe`` will also let each branch run its
own side effect (``func``) on every ``item`` without touching the main ``pipeline``.


Compiling workflow documents
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In addition to running Python pipe scripts and workflow modules, ``riko`` can run
JSON workflow documents (``WorkflowDocument``\s). The simplest way to author a
``Workflow`` is a *bare-bones DAG* (``PipeDag``), which ``parse_dag`` expands. It is a
list of ``modules`` plus optional wires. When ``wires`` are omitted the modules are
chained linearly and blank ``id``\s default to ``sw-{n}``. Each wire is a
``[source, target]`` pair, optionally followed by the port it enters. This makes fan-in
operators such as ``union``/``join`` expressible too.

.. code-block:: python

    >>> from riko import Pipeline, parse_dag
    >>>
    >>> ### Author a terse, linear DAG (no wires, no ids) ###
    >>> itembuilder_conf = {'attrs': {'key': 'greeting', 'value': 'hello'}}
    >>> rename_conf = {'rule': {'field': 'greeting', 'newval': 'salutation'}}
    >>> dag = {
    ...     'modules': [
    ...         {'name': 'itembuilder', 'conf': itembuilder_conf},
    ...         {'name': 'rename', 'conf': rename_conf},
    ...     ]
    ... }
    >>>
    >>> ### Expand it into a validated Workflow and run it ###
    >>> flow = parse_dag(dag)
    >>> list(Pipeline(flow))
    [{'salutation': 'hello'}]

``compile_workflow`` turns the same ``Workflow`` into a workflow module
(``WorkflowModule``): the Python source of a module that rebuilds it. The module
declares the graph with typed configuration classes. E.g., a ``sort`` node's ``conf``
becomes a ``SortRawConf``, so a type checker catches a bad option.

The module also exposes a single ``pipe`` (or, with ``is_async=True``, an
``async_pipe``) callable that runs the workflow through riko's execution with the
``Context`` you hand it. It is ordinary importable Python that you can edit it or save
as ``pipe_<id>.py`` in a package. Register the pacakage with
``riko.ext.register_workflow_store`` so a ``loop`` can embed it by the saved name.

.. code-block:: python

    >>> from riko import compile_workflow
    >>>
    >>> source = compile_workflow(flow, 'pipe_demo')
    >>> print(next(l for l in source.splitlines() if l.startswith('DEPENDENCIES')))
    DEPENDENCIES: list[str] = ["itembuilder", "rename"]
    >>> print(next(l for l in source.splitlines() if l.startswith('pipe')))
    pipe = build_workflow_pipes(

The ``build-workflow``, ``compile-workflow``, and ``run-pipe`` commands work on the same
forms stored as files: ``build-workflow`` expands a serialized ``PipeDag`` into a
``WorkflowDocument``, ``run-pipe -p flow.json`` executes one, and ``compile-workflow`` emits
the ``WorkflowModule`` above.

.. code-block:: bash

    build-workflow dag.json -o flow.json
    compile-workflow flow.json -o flow.py
    run-pipe -p flow.json

``build-workflow`` also converts a serialized pipe definition (``PipeDef``, the older
``{"src": ..., "tgt": ...}`` wire format). ``compile-workflow`` takes ``WorkflowDocument``\s
only. ``run-pipe -p`` runs a ``WorkflowDocument``, a ``WorkflowModule`` such as
``flow.py``, or a pipe script (a Python file that defines ``pipe(test=False)``).

See the `DAG format doc`_ for the complete schema and expansion rules, and the FAQ's
`Can I store a workflow as JSON`_ for chaining ``build-workflow`` into
``compile-workflow`` through stdin.

Running stored workflows
^^^^^^^^^^^^^^^^^^^^^^^^

A stored workflow is one that ``riko`` finds by its ``pipe_<id>`` name. Tell ``riko``
where to look with ``riko.ext.register_workflow_store``. ``package=`` imports a
package's ``pipe_<id>.py`` files, i.e., saved workflow modules (``WorkflowModule``\s).
``directory=`` reads a directory's ``pipe_<id>.json`` workflow documents
(``WorkflowDocument``\s).

Run a stored workflow by name with ``Pipeline.from_module``, or embed it in a ``loop``.
You can also use ``pipe:<id>`` as an alias for ``pipe_<id>``.

.. code-block:: python

    >>> from pathlib import Path
    >>> from tempfile import TemporaryDirectory
    >>> from riko import Pipeline
    >>> from riko.ext import register_workflow_store, serialize_workflow
    >>>
    >>> conf = {'attrs': {'key': 'greeting', 'value': 'hello'}}
    >>> greet = Pipeline.from_module('itembuilder', conf=conf)
    >>>
    >>> with TemporaryDirectory() as tmp:
    ...     document = Path(tmp) / 'pipe_greet.json'
    ...     _ = document.write_bytes(serialize_workflow(greet.workflow))
    ...     register_workflow_store(directory=Path(tmp), replace=True)
    ...     list(Pipeline.from_module('pipe:greet'))
    [{'greeting': 'hello'}]

Notes:

- If the package has ``pipe_greet.py`` and the directory has ``pipe_greet.json``, the
  package's file wins.

- Registering a second package or directory raises ``ValueError`` unless you pass
  ``replace=True``.

- ``riko.ext.registry.reset_workflow_resolver()`` unregisters the package and the
  directory. No stored workflow will be found until you register one again.

- Running a ``pipe_<id>`` that neither has raises ``UnsupportedWorkflowError``.

Inspecting a pipeline
^^^^^^^^^^^^^^^^^^^^^

You can introspect a workflow *without running it*. Its nodes name the modules
the ``pipeline`` uses — handy for validating that every required ``module`` is
installed before execution.

.. code-block:: python

    >>> from riko import parse_dag
    >>>
    >>> itembuilder_conf = {'attrs': {'key': 'greeting', 'value': 'hi'}}
    >>> rename_conf = {'rule': {'field': 'greeting', 'newval': 'salutation'}}
    >>> dag = {
    ...     'modules': [
    ...         {'name': 'itembuilder', 'conf': itembuilder_conf},
    ...         {'name': 'rename', 'conf': rename_conf},
    ...     ]
    ... }
    >>> flow = parse_dag(dag)
    >>> sorted(node.name for node in flow.nodes.values())
    ['itembuilder', 'rename']

A *compiled* workflow module's ``pipe`` function (see `Compiling workflow documents`_)
can additionally report its input declarations or dependencies (the modules and stored
workflows it uses) at run time.

Pass a ``Context`` whose ``mode`` is ``ExecutionMode.DESCRIBE_INPUTS`` or
``DESCRIBE_DEPENDENCIES`` and the generated ``pipe()`` will return the input
declarations or list of module and stored-workflow names instead of running.
``DESCRIBE`` returns both as a mapping with ``inputs`` and ``dependencies`` keys.

.. code-block:: python

    >>> from riko import Context, ExecutionMode, compile_workflow
    >>>
    >>> namespace = {}
    >>> exec(compile_workflow(flow, 'pipe_demo'), namespace)
    >>> pipe = namespace['pipe']
    >>> pipe(context=Context(mode=ExecutionMode.DESCRIBE_DEPENDENCIES))
    ['itembuilder', 'rename']
    >>> pipe(context=Context(mode=ExecutionMode.DESCRIBE))
    {'inputs': {}, 'dependencies': ['itembuilder', 'rename']}

Performance and memory
----------------------

Keep the following execution behaviors in mind:

- A ``Pipeline`` is a definition. Every iteration is a fresh execution, so iterating
  twice does the work twice. Materialize with ``export`` or ``list`` when you need to
  reuse a result.
- Most modules are lazy, but ``write``, ``sort``, ``reverse``, ``count``, and ``sum``
  with a ``group_key`` hold the whole ``stream`` in memory. None of these can run on an
  unbounded source. See the `FAQ`_ for the full table of what each retains.
- By default, ``processors`` process one ``item`` at a time, whether
  iterated sync or async. Use ``with_execution`` to set ``concurrency``. This does not affect
  ``operators`` such as ``sort``/``count``.
- Parallel execution is unordered by default. Ordering can reduce throughput since slow
  items can block the entire stream. See `Bounded parallelism`_ for how far ahead the
  ``source`` is pulled.
- ``split`` and ``publish``/``subscribe`` are fan-out and raise ``NotImplementedError``
  until streaming fan-out and local subscriptions land (see `Fanning out a stream`_).
- Don't infer that parallel execution is faster. Measure the actual workload;
  pool startup, serialization, ordering, and I/O behavior can dominate small
  pipelines.

For dataframe-scale columnar analytics, a dataframe engine such as Pandas or
Polars may be a better fit. For distributed execution or durable orchestration,
run ``riko`` inside the relevant worker or task rather than treating ``riko`` as
the scheduler.

.. _FAQ: FAQ.rst
.. _discovering modules: FAQ.rst#how-do-i-discover-installed-modules
.. _Can I create custom modules: FAQ.rst#can-i-create-custom-modules
.. _Can I store a workflow as JSON: FAQ.rst#can-i-store-a-workflow-as-json
.. _riko-example-ext: ../examples/riko-example-ext
.. _register_module.py: ../examples/register_module.py
.. _register_alias.py: ../examples/register_alias.py
.. _Design Principles: ../README.rst#design-principles
.. _Pipeline chaining: ../README.rst#synchronous-processing
.. _DAG format doc: DAG_FORMAT.rst
