riko Cookbook
=============

This cookbook presents ``riko`` recipes from basic iterator pipelines through
asynchronous execution, custom modules, testing, and JSON ``pipeline`` compilation.
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

    >>> from riko import Sources, SyncPipe
    >>>
    >>> conf = {'attrs': {'key': 'content', 'value': 'a,bb,ccc'}}
    >>> flow = (
    ...     SyncPipe(Sources.ITEMBUILDER, conf=conf)
    ...     .tokenizer(emit=True)
    ...     .count()
    ... )
    >>> next(flow)
    {'count': 3}

``SyncPipe`` resolves each chained attribute as a built-in ``pipe``. Its first argument
can be either a string or (as shown above) a member of the typed discovery tree
(``Sources``/``Transforms``/``Sinks``). The ``flow`` is lazy, so it does no work until
it is consumed (i.e., by ``list()``, teration, ``next()``, or an export). See
`discovering modules`_ in the FAQ for ``list_modules`` and``describe_module``.

Transform, filter, and order items
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The next ``flow`` keeps scores greater than 10, creates a slug from each title,
and orders the results by score.

.. code-block:: python

    >>> from riko import SyncPipe
    >>>
    >>> items = [
    ...     {'title': 'Draft report', 'score': 8},
    ...     {'title': 'Final report', 'score': 21},
    ...     {'title': 'Release notes', 'score': 13}]
    >>> rule = {'field': 'score', 'op': 'greater', 'value': 10}
    >>> replace = {'rule': {'find': ' ', 'replace': '-'}}
    >>> flow = (
    ...     SyncPipe(source=items)
    ...         .filter(conf={'rule': rule})
    ...         .strreplace(conf=replace, field='title', assign='slug')
    ...         .sort(conf={'rule': {'field': 'score'}}))
    >>> [(item['slug'], item['score']) for item in flow]
    [('Release-notes', 13), ('Final-report', 21)]

``field`` selects the input field passed to a ``processor``. ``assign`` names
the field receiving the result. Passing ``emit=True`` instead yields the
processed value as a new ``item`` rather than assigning it to the original.

Combine multiple rules
^^^^^^^^^^^^^^^^^^^^^^

``filter`` accepts one rule or a list of rules. ``combine`` is ``and`` by
default and can be set to ``or``.

.. code-block:: python

    >>> from riko import SyncPipe
    >>>
    >>> items = [
    ...     {'title': 'Alpha', 'score': 5, 'published': True},
    ...     {'title': 'Beta', 'score': 15, 'published': False},
    ...     {'title': 'Gamma', 'score': 20, 'published': True}]
    >>> rules = [
    ...     {'field': 'score', 'op': 'atleast', 'value': 10},
    ...     {'field': 'published', 'op': 'truthy'}]
    >>> flow = SyncPipe(source=items).filter(conf={'rule': rules})
    >>> [item['title'] for item in flow]
    ['Gamma']

Set ``permit=False`` to exclude matches instead of keeping them.

Read structured data
^^^^^^^^^^^^^^^^^^^^

``get_path`` resolves files bundled in ``riko/data`` and makes documentation
examples deterministic.

.. code-block:: python

    >>> from riko import Sources, SyncPipe, get_path
    >>>
    >>> flow = SyncPipe(Sources.FETCHDATA, conf={'url': get_path('quote.json')})
    >>> next(flow)['base']
    'USD'

Use ``fetchdata`` for JSON or XML records, ``csv`` for CSV parsing, and
``fetchtable`` for supported tabular formats. See the `FAQ`_ for the full format
matrix and each ``pipe`` configuration.

Read feeds
^^^^^^^^^^

``fetch`` normalizes RSS or Atom entries into dictionary-like ``items``.

.. code-block:: python

    >>> from riko import Sources, SyncPipe, get_path
    >>>
    >>> flow = SyncPipe(Sources.FETCH, conf={'url': get_path('feed.xml')})
    >>> item = next(flow)
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

    >>> from riko import Sources, SyncPipe, get_path
    >>>
    >>> flow = (
    ...     SyncPipe(
    ...         Sources.FETCHPAGE,
    ...         conf={
    ...             'url': get_path('users.jyu.fi.html'),
    ...             'start': '<body>',
    ...             'end': '</body>',
    ...             'detag': True})
    ...         .strreplace(
    ...             conf={'rule': {'find': '\n', 'replace': ' '}},
    ...             assign='content')
    ...         .tokenizer(conf={'delimiter': ' '}, emit=True)
    ...         .count())
    >>> list(flow)
    [{'count': 70}]

Use ``fetchtext`` for plain text files and ``xpathfetchpage`` when XPath-based
selection is required and the relevant parser dependency is installed.

User input
^^^^^^^^^^

Some ``pipelines`` require user input (via the ``input`` pipe). By default,
``input`` prompts the user via the console, but in some situations this may not
be appropriate, e.g., testing or integrating with a website. In such cases, the
input values can instead be read from a ``pipeline`` ``inputs`` kwarg (a set
of values passed into every ``pipe``).

.. code-block:: python

    >>> from riko import Sources, SyncPipe
    >>>
    >>> conf = {'prompt': 'How old are you?', 'type': 'int'}
    >>> next(SyncPipe(Sources.INPUT, conf=conf, inputs={'content': '30'}))
    30

Intermediate recipes
--------------------

Fetching data and feeds
^^^^^^^^^^^^^^^^^^^^^^^

``riko`` can read both local and remote filepaths via ``source`` pipes. All
``source`` pipes return an equivalent ``stream`` iterator of dictionaries, aka
``items``.

.. code-block:: python

    >>> from riko import get_path, Sources, SyncPipe
    >>>
    >>> # Note: `get_path` looks up a cached copy of a URL in the `data`
    >>> # directory, so these examples run offline
    >>>
    >>> ### Fetch a web page ###
    >>> stream = SyncPipe(Sources.FETCHPAGE, conf={'url': get_path('users.jyu.fi.html')})
    >>>
    >>> ### Fetch a data file ###
    >>> stream = SyncPipe(Sources.FETCHDATA, conf={'url': get_path('quote.json')})
    >>>
    >>> ### View the fetched data ###
    >>> item = next(stream)
    >>> item['base']
    'USD'
    >>> ### Fetch an RSS feed ###
    >>> stream = SyncPipe(Sources.FETCH, conf={'url': get_path('feed.xml')})
    >>>
    >>> ### Fetch the first RSS feed found on a page ###
    >>> stream = SyncPipe(Sources.FETCHSITEFEED, conf={'url': get_path('cnn.html')})
    >>>
    >>> ### Find all RSS links on a page and fetch the feeds ###
    >>> entries = SyncPipe(Sources.FEEDAUTODISCOVERY, conf={'url': get_path('bbc.html')})
    >>> urls = [entry['link'] for entry in entries]
    >>> urls
    ['file://riko/data/bbci.co.uk.xml']
    >>> stream = SyncPipe(Sources.FETCH, conf={'url': urls[0]})
    >>>
    >>> ### Alternatively, create a SyncCollection ###
    >>> #
    >>> # `SyncCollection` is a URL fetching convenience class with support for
    >>> # parallel processing
    >>> from riko import SyncCollection
    >>>
    >>> sources = [{'url': url} for url in urls]
    >>> stream = SyncCollection(sources)
    >>>
    >>> ### View the fetched RSS feed(s) ###
    >>> #
    >>> # Note: regardless of how you fetch an RSS feed, it will have the same
    >>> # structure
    >>> next(stream)['title']
    "EU sets out 'phased' Brexit strategy"

Alternate ``conf`` value entry
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Some ``pipelines`` have ``conf`` values that are wired from other ``pipes``. A
``conf`` value can reference a field on the current ``item`` with ``subkey``.
This is how compiled ``pipelines`` wire values between modules.

.. code-block:: python

    >>> from riko import get_path, Sources, SyncPipe
    >>>
    >>> conf = {'url': {'subkey': 'url'}}
    >>> items = [{'url': get_path('feed.xml')}]
    >>> result = SyncPipe(Sources.FETCH, items, conf=conf)
    >>> item = next(result)
    >>> {'author', 'content', 'id', 'link', 'published', 'summary', 'title'} <= set(item)
    True

Alternate pipeline creation
^^^^^^^^^^^^^^^^^^^^^^^^^^^

In addition to `class based flows`_ ``riko`` supports a pure functional
style [#]_. Every built-in ``pipe`` can also be called directly, which is useful
when control flow is easier to express explicitly.

.. warning::

   Direct module imports are implementation-level APIs and are not covered by
   the stable API guarantee. Application code that needs the stable public surface
   should prefer ``SyncPipe`` or ``AsyncPipe``.

.. code-block:: python

    >>> from riko import get_path
    >>> from riko.modules.fetchpage import pipe as fetchpage
    >>> from riko.modules.strreplace import pipe as strreplace
    >>> from riko.modules.tokenizer import pipe as tokenizer
    >>> from riko.modules.count import pipe as count
    >>>
    >>> ### Set the pipe configurations ###
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

.. [#] See `Design Principles`_ for explanation on `pipe` types and sub-types

Chaining with the ``|`` operator or ``pipe`` method
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Alongside attribute chaining (``pipe.tokenizer(...)``), a ``pipe`` can be added to the
``pipeline`` with the ``|`` operator or the ``pipe`` method. These take the module name
as either a string or a typed ``Sources``/``Transforms``/``Sinks`` member. They also
accept dynamic or dotted name modules, e.g., ``"microsoft.autopilot.ensure"``.

.. code-block:: python

    >>> from riko import SyncPipe, Transforms
    >>>
    >>> src = [{"content": "a,b,c,a"}]
    >>>
    >>> # seed a source stream with ``items | pipe``
    >>> next(src | SyncPipe(Transforms.TOKENIZER))
    {'content': 'a'}
    >>>
    >>> # chain a pipe by name
    >>> tokens = SyncPipe(Transforms.TOKENIZER, source=src)
    >>> next(tokens | Transforms.HASH)
    {'content': 'a', 'hash': 1267964084}
    >>>
    >>> # chain a pipe by ``(name, conf)`` pair
    >>> tokens = SyncPipe(Transforms.TOKENIZER, source=src)
    >>> list(tokens | (Transforms.TRUNCATE, {"count": 2}))
    [{'content': 'a'}, {'content': 'b'}]
    >>>
    >>> # chain with a dynamic pipe name
    >>> module = "count"
    >>> tokens = SyncPipe(Transforms.TOKENIZER, source=src).pipe(module)
    >>> next(tokens)
    {'count': 4}

Fetch several sources
^^^^^^^^^^^^^^^^^^^^^

``SyncCollection`` merges ``items`` from multiple configured sources. A source
uses ``fetch`` by default; set its ``type`` key to select another ``source``
module.

.. code-block:: python

    >>> from riko import SyncCollection, get_path
    >>>
    >>> sources = [{'url': get_path('feed.xml')}, {'url': get_path('gawker.xml')}]
    >>> len(list(SyncCollection(sources)))
    32

For concurrent local fetching, use ``parallel=True``. The default pool uses
threads; pass ``threads=False`` for processes.

.. code-block:: python

    >>> with SyncCollection(sources, parallel=True, workers=4) as collection:
    ...     len(list(collection))
    32

Managing pipeline lifecycle
^^^^^^^^^^^^^^^^^^^^^^^^^^^

A ``SyncPipe``/``AsyncPipe`` (and the ``SyncCollection``/``AsyncCollection``
classes) represents a *single* execution. Iterating it consumes the underlying
``stream``; iterating again yields an empty ``stream`` rather than silently
re-running. You can inspect a pipe's state at any point via its read-only
``state``/``closed``/``exhausted``/``failed`` properties.

.. code-block:: python

    >>> from riko import SyncPipe, Transforms
    >>>
    >>> flow = SyncPipe(Transforms.HASH, source=[{'content': 'a'}, {'content': 'b'}])
    >>> flow.state
    <PipeState.NEW: 'new'>
    >>> len(list(flow))                    # consume the stream
    2
    >>> flow.exhausted, flow.state
    (True, <PipeState.EXHAUSTED: 'exhausted'>)
    >>> list(flow)                         # re-iterating yields nothing
    []

Chaining after partial consumption wraps only the remaining ``source``.

.. code-block:: python

    >>> flow = SyncPipe(Transforms.HASH, source=[{'content': 'a'}, {'content': 'b'}])
    >>> next(flow)['content']
    'a'
    >>> list(flow.count())
    [{'count': 1}]

Parallel pipes own a worker pool. Use the pipe as a context manager (or call
``close()``/``terminate()``) to release it deterministically — on normal exit
the pool is closed; on exceptional exit it is terminated.

.. code-block:: python

    >>> with SyncPipe(Transforms.HASH, source=[{'content': 'a'}], parallel=True) as flow:
    ...     list(flow)
    [{'content': 'a', 'hash': 1267964084}]
    >>> flow.closed and flow.pool is None  # pool released on exit
    True

Exporting results
^^^^^^^^^^^^^^^^^

A ``flow`` is a lazy, single-use iterator. ``export()`` materializes it into a
concrete list you can index, measure, and reuse.

.. code-block:: python

    >>> from riko import SyncPipe, Transforms
    >>>
    >>> flow = SyncPipe(Transforms.HASH, source=[{'title': 'a'}, {'title': 'b'}])
    >>> items = flow.export()
    >>> len(items), items[0]['title']      # unlike the flow, indexable & measurable
    (2, 'a')

You can pass a target as the first argument to change the export type. The target may be
a plain string or a member of the typed ``Targets`` enum (recommended, for editor
autocompletion). ``list_targets()`` lists the targets available at
runtime (``ofx``/``qif`` require the optional ``csv2ofx`` dependency).

    >>> from riko import Targets, list_targets
    >>>
    >>> source= [{"title": "a"}, {"title": "b"}]
    >>> flow = SyncPipe(Transforms.HASH, source=source, field="title")
    >>> {"csv", "geojson", "json", "list", "tuple"}.issubset(list_targets())
    True
    >>> flow.export("tuple")
    ({'title': 'a', 'hash': 1267964084}, {'title': 'b', 'hash': 2297772648})
    >>> flow = SyncPipe(Transforms.HASH, source=source, field="title")
    >>> flow.export(Targets.JSON)
    '[{"hash": 1267964084, "title": "a"}, {"hash": 2297772648, "title": "b"}]'


For serialized output, you can pass a file path or file like object as the second
argument.

``export()`` is a one-shot terminal call. To write **inside** a pipeline uninterrupted,
use the ``write`` sink pipe: it serializes the stream to ``conf['url']`` with a
``Targets`` converter (``target`` defaults to ``'json'``) and passes every item through
unchanged. This allows you can persist an intermediate result and continue processing.

.. code-block:: python

    >>> from riko import get_temp_file, SyncPipe, Sources
    >>>
    >>> conf = {"attrs": {"key": "content", "value": "a,bb,ccc"}}
    >>> with get_temp_file() as fp:
    ...     flow = (
    ...         SyncPipe(Sources.ITEMBUILDER, conf=conf)
    ...         .tokenizer()
    ...         .write(conf={"url": fp.name})
    ...         .count()
    ...     )
    ...     next(flow)
    ...     fp.read()
    {'count': 3}
    b'[{"content": "a"}, {"content": "bb"}, {"content": "ccc"}]'

Note that both ``export`` and ``write`` are **eager**: they serialize the complete
source stream into memory. Don't use them on an unbounded ``stream``.

Asynchronous pipelines
----------------------

The ``async`` extra (``python -m pip install "riko[async]"``) enables ``AsyncPipe`` and
``AsyncCollection``, which mirror their synchronous counterparts. Build a
``flow`` the same way, then either ``await`` it (materializing the whole
``stream``) or consume it lazily with ``async for``. ``riko.run`` executes
a coroutine on the installed backend, and ``issync`` is ``True`` when no async
backend is present (so these examples degrade gracefully when the extra is
absent).

Each async ``source`` fetch reads its body fully into memory before parsing (a
single ``await``). So ``stream`` here means ``Iterator[item]``, not an incremental
network read. Bounded parallelism (below) keeps the *item* ``stream`` from being
materialized up front, but each individual body is still buffered whole.

Lazy async iteration
^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    >>> from riko import AsyncPipe, Sources, get_path, issync, run
    >>>
    >>> fetch_conf = {'url': get_path('feed.xml')}
    >>> filter_rule = {'field': 'title', 'op': 'contains', 'value': 'a'}
    >>>
    >>> ### Consume an AsyncPipe item-by-item with `async for` ###
    >>> async def main():
    ...     pipe = (
    ...         AsyncPipe(Sources.FETCH, conf=fetch_conf).filter(conf={'rule': filter_rule})
    ...     )
    ...     titles = [item['title'] async for item in pipe]
    ...     print(titles[0], '/', len(titles))
    >>>
    >>> print('Donations / 5') if issync else run(main)
    Donations / 5

Fetching feeds concurrently
^^^^^^^^^^^^^^^^^^^^^^^^^^^

``AsyncCollection`` is the async counterpart of ``SyncCollection``: it fetches
every source concurrently and merges them into a single ``stream``.

.. code-block:: python

    >>> from riko import AsyncCollection, get_path, issync, run
    >>>
    >>> async def main():
    ...     sources = [{'url': get_path('feed.xml')}, {'url': get_path('gawker.xml')}]
    ...     coll = AsyncCollection(sources)
    ...     print(len([item async for item in coll]))
    >>>
    >>> print(32) if issync else run(main)
    32

Bounded parallelism
^^^^^^^^^^^^^^^^^^^

Passing ``parallel=True`` maps a ``pipe`` over its ``source`` with bounded
concurrency and backpressure, so large or streaming sources are never
materialized up front. Pass ``ordered=True`` to preserve source order (the
default is unordered — results arrive as they complete) and ``connections`` to
cap the number of in-flight items.

.. code-block:: python

    >>> from riko import AsyncPipe, Sources, issync, run
    >>>
    >>> async def main():
    ...     conf = {'attrs': {'key': 'content', 'value': 'a,bb,ccc'}}
    ...     pipe = (
    ...         AsyncPipe(Sources.ITEMBUILDER, conf=conf, parallel=True)
    ...         .tokenizer(emit=True)
    ...         .hash()
    ...     )
    ...     print([item['content'] async for item in pipe])
    >>>
    >>> print(['a', 'bb', 'ccc']) if issync else run(main)
    ['a', 'bb', 'ccc']

The default is unordered completion. Set ``ordered=True`` only when source order
is part of the result contract. ``prefetch`` adds a result buffer beyond the
in-flight connection limit.

Advanced recipes
----------------

Handling errors
^^^^^^^^^^^^^^^

Module exceptions propagate to the caller and mark the ``flow`` as failed.
Re-iteration then yields an empty ``stream``, and attempting to chain a failed
``flow`` raises ``PipelineStateError``.

.. code-block:: python

    >>> from riko import PipelineStateError, SyncPipe, Transforms
    >>>
    >>> def broken_source():
    ...     yield {'content': 'first'}
    ...     raise RuntimeError('broken input')
    >>>
    >>> flow = SyncPipe(Transforms.HASH, source=broken_source())
    >>> try:
    ...     list(flow)
    ... except RuntimeError as exc:
    ...     print(exc)
    broken input
    >>> flow.failed
    True
    >>> try:
    ...     flow.count()
    ... except PipelineStateError as exc:
    ...     print(exc.action, exc.state)
    chain failed

Chaining onto a ``closed`` ``flow`` is also terminal:

.. code-block:: python

    >>> flow = SyncPipe(Transforms.HASH, source=[{'content': 'a'}])
    >>> flow.close()
    >>> flow.closed
    True
    >>> try:
    ...     flow.count()
    ... except PipelineStateError:
    ...     print('cannot chain a closed flow')
    cannot chain a closed flow

``riko`` doesn't provide a general retry policy or durable recovery layer. Put
retryable I/O behind a function or module with an explicit policy, or run
``riko`` inside an orchestrator when task-level retries and persistence are
required.

Using a one-off function
^^^^^^^^^^^^^^^^^^^^^^^^

The built-in ``udf`` ``processor`` applies a Python callable to each ``item``.
It is the simplest option when a transformation is local to one application.

.. code-block:: python

    >>> from riko import SyncPipe, Transforms
    >>>
    >>> def add_length(item):
    ...     return {**item, 'length': len(item['content'])}
    >>>
    >>> items = [{'content': 'a'}, {'content': 'abcd'}]
    >>> flow = SyncPipe(Transforms.UDF, source=items, func=add_length, emit=True)
    >>> [item['length'] for item in flow]
    [1, 4]

Use the extension decorators when the transformation should have normal ``riko``
configuration, assignment, metadata, and sync/async wrappers.

Creating a custom processor
^^^^^^^^^^^^^^^^^^^^^^^^^^^

``processor`` wraps a function that handles one ``item`` at a time. A decorated
callable can be invoked functionally, or registered so ``SyncPipe`` resolves it
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
`register_module.py`_ do). Pass ``isasync=True`` explicitly if you wrap a sync function
(that isn't named ``async_pipe``) for the async interface.

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

To make a custom module resolvable by name, i.e., ``SyncPipe('your.module', ...)``
and the ``|`` operator find it, register it with ``riko.ext.register`` or declare
a ``[project.entry-points."riko.modules"]`` entry point. Point a ``ModuleDefinition``
at a module exposing ``pipe``/``async_pipe``, or pass those callables explicitly. See
`riko-example-ext`_ (installable entry-point plugin), `register_module.py`_ (runtime
``register`` with explicit callables), and `register_alias.py`_ (runtime ``register``
aliasing a built-in), plus the `FAQ`_ entry `Can I create custom modules`_ for the
mechanics.

Fanning out a stream
^^^^^^^^^^^^^^^^^^^^

Sometimes you need to consume the same ``stream`` from multiple independent pipelines.
For example, archiving every item while also sending urgent items, to an alert queue.
Consuming the iterator twice would exhaust it, and materialising it into a list defeats
lazy evaluation. ``riko`` solves this with ``publish`` and ``subscribe``:

.. code-block:: python

    >>> from riko import SyncPipe, Transforms
    >>>
    >>> items = [{'title': 'Gravity paper'}, {'title': 'Breaking: riko 4.0'}]
    >>> subscriber = SyncPipe.subscribe('subscriber')
    >>> publisher = SyncPipe.publish(items, 'subscriber')
    >>>
    >>> ### Consuming the publisher drives the push ###
    >>> _ = list(publisher)
    >>>
    >>> ### Drain the subscriber independently ###
    >>> [item['title'] for item in subscriber]
    ['Gravity paper', 'Breaking: riko 4.0']

``publish`` composes naturally in a ``SyncPipe`` chain via ``.publish(...)``.
The stream continues down the main pipeline while a copy flows to each named
subscriber:

.. code-block:: python

    >>> from riko import SyncPipe, Transforms
    >>>
    >>> ### `archive` and `notify` stand in for your real side effects ###
    >>> archived, alerted = [], []
    >>> everything = SyncPipe.subscribe('everything', func=archived.append)
    >>> breaking = SyncPipe.subscribe('breaking', func=alerted.append)
    >>>
    >>> items = [
    ...     {'title': 'quiet', 'score': 42},
    ...     {'title': 'breaking: riko 4.0', 'score': 980},
    ...     {'title': 'also big', 'score': 750}
    ... ]
    >>>
    >>> ### Send ALL items to 'everything', filter, then send matches to 'breaking' ###
    >>> flow = (
    ...     SyncPipe(source=items)
    ...         .publish('everything')
    ...         .filter(conf={'rule': [{'field': 'score', 'value': 500, 'op': 'greater'}]})
    ...         .publish('breaking')
    ...         .sort(conf={'rule': [{'field': 'score'}]})
    ... )
    >>>
    >>> ### Consume the main pipeline (this also drives the pushes) ###
    >>> [item['title'] for item in flow]  # sorted high score items
    ['also big', 'breaking: riko 4.0']
    >>>
    >>> ### Subscriber funcs already ran as items were published ###
    >>> [item['title'] for item in archived]  # all items in original order
    ['quiet', 'breaking: riko 4.0', 'also big']
    >>> [item['title'] for item in alerted]  # high score items in original order
    ['breaking: riko 4.0', 'also big']
    >>>
    >>> ### Drain and discard subscriber output after publishing is complete ###
    >>> _ = list(breaking)
    >>> _ = list(everything)

You can publish to multiple subscribers by passing additional names:

.. code-block:: python

    >>> publisher = SyncPipe.publish(items, 'breaking', 'archive', 'metrics')

Each subscriber is drained independently; draining one does not affect the others.

``split`` vs ``publish``/``subscribe``
''''''''''''''''''''''''''''''''''''''

``riko`` also has a ``split`` pipe that copies a stream for multiple consumers:

.. code-block:: python

    >>> from riko import SyncPipe, Transforms
    >>>
    >>> items = [{'title': 'riko pt. 1'}, {'title': 'riko pt. 2'}]
    >>> stream1, stream2 = SyncPipe(Transforms.SPLIT, items)
    >>> next(stream1), next(stream2)
    ({'title': 'riko pt. 1'}, {'title': 'riko pt. 1'})

The difference between them is that ``split`` calls ``list(stream)`` internally, so it
**eagerly materializes** the ``stream`` into memory before handing out copies.
``publish``/``subscribe`` are **lazy**: item are pushed to subscribers as it passes
through, with no upfront buffering.

+-------------------------------+---------------------------+----------------------------+
| Dimension                     | ``split``                 | ``publish`` / ``subscribe``|
+===============================+===========================+============================+
| Evaluation                    | Eager — full stream in    | Lazy — one item at a time  |
|                               | memory before any copy    |                            |
+-------------------------------+---------------------------+----------------------------+
| Memory (best case)            | O(n) — source items       | O(queue size, default 256) |
|                               | retained; branches        |                            |
|                               | deep-copy lazily as       |                            |
|                               | consumed                  |                            |
+-------------------------------+---------------------------+----------------------------+
| Memory (worst case)           | O(n × branches) —         | O(queue size, default 256) |
|                               | materializing every       |                            |
|                               | branch downstream         |                            |
+-------------------------------+---------------------------+----------------------------+
| Infinite / very large streams | Hangs or OOM              | Works                      |
+-------------------------------+---------------------------+----------------------------+
| API                           | Returns N iterators       | Subscribers drained        |
|                               | in one call               | independently              |
+-------------------------------+---------------------------+----------------------------+
| Transform per branch          | No. Identical copies.     | Yes. ``func=`` in each     |
|                               |                           | ``subscribe``              |
+-------------------------------+---------------------------+----------------------------+
| SyncPipe chain                | Returns N streams;        | ``.publish(...)`` stays in |
|                               | not chainable             | the chain                  |
+-------------------------------+---------------------------+----------------------------+

**Use** ``split`` when the stream is small and finite and you want the simplest
possible API.

**Use** ``publish``/``subscribe`` when the stream is large, potentially infinite, or
when the main pipeline must stay lazy (e.g., inside a ``timeout`` or ``truncate``
composer). ``subscribe`` also lets you apply a different transform (``func``)
to the branched items without touching the main flow.

.. _ijson: https://github.com/ICRAR/ijson/blob/master/notes/design_notes.rst


Compiling JSON pipelines
^^^^^^^^^^^^^^^^^^^^^^^^

In addition to writing ``pipelines`` in Python, ``riko`` can load and compile
``pipelines`` stored as JSON pipe definitions (the Yahoo! Pipes-style
``{"modules": [...], "wires": [...]}`` format). The simplest way to author one
is as a *bare-bones DAG* — a list of ``modules`` plus optional
``[source, target]`` wire pairs. When ``wires`` are omitted the modules are
chained linearly, and a missing ``id`` defaults to ``sw-{n}``.

.. code-block:: python

    >>> from riko import Context, convert_dag, build_pipeline, parse_pipe_def
    >>>
    >>> ### Author a terse, linear DAG (no wires, no ids) ###
    >>> itembuilder_conf = {'attrs': {'key': 'greeting', 'value': 'hello'}}
    >>> rename_conf = {'rule': {'field': 'greeting', 'newval': 'salutation'}}
    >>> dag = {
    ...     'modules': [
    ...         {'type': 'itembuilder', 'conf': itembuilder_conf},
    ...         {'type': 'rename', 'conf': rename_conf},
    ...     ]
    ... }
    >>>
    >>> ### Expand it into a full JSON pipe definition ###
    >>> #
    >>> # `convert_dag` appends the terminal `output` node, wires the modules in
    >>> # listing order, and connects the final sink to `_OUTPUT`.
    >>> pipe_def = convert_dag(dag)
    >>>
    >>> ### Execute it in-process ###
    >>> stream = build_pipeline(parse_pipe_def(pipe_def, 'pipe_demo'), context=Context())

To instead emit a standalone, runnable Python module (equivalent to the
``compile-pipe`` CLI), use ``compile_pipe``:

.. code-block:: python

    >>> from riko import compile_pipe
    >>>
    >>> source = compile_pipe(pipe_def, 'pipe_demo')
    >>> 'def pipe' in source
    True

Or use the command-line tools:

.. code-block:: bash

    convert-dag flow.dag.json -o flow.json
    compile-pipe flow.json -o flow.py

Or chain them, since ``compile-pipe`` reads stdin when given ``-`` (or no path):

.. code-block:: bash

    convert-dag flow.dag.json | compile-pipe - -o flow.py -v

Note that fan-in operators such as ``union``/``join`` cannot be expressed with
the ``[source, target]`` pair format (their secondary inputs need ``_OTHER{n}``
targets) and must be authored as a full JSON pipe definition instead. See the
`DAG format doc`_ for the complete schema and expansion rules.

Inspecting a pipeline
^^^^^^^^^^^^^^^^^^^^^

You can introspect a JSON pipe definition *without running it*.
``extract_dependencies`` returns the sorted set of modules a ``pipeline`` uses —
handy for validating that every required ``pipe`` is installed before execution.

.. code-block:: python

    >>> from riko import convert_dag, extract_dependencies
    >>>
    >>> itembuilder_conf = {'attrs': {'key': 'greeting', 'value': 'hi'}}
    >>> rename_conf = {'rule': {'field': 'greeting', 'newval': 'salutation'}}
    >>> dag = {
    ...     'modules': [
    ...         {'type': 'itembuilder', 'conf': itembuilder_conf},
    ...         {'type': 'rename', 'conf': rename_conf},
    ...     ]
    ... }
    >>> extract_dependencies(convert_dag(dag))
    ['itembuilder', 'rename']

A *compiled* pipeline (see `Compiling JSON pipelines`_) can additionally report
its input requirements or module dependencies at run time — pass a ``Context``
whose ``mode`` is ``ExecutionMode.DESCRIBE_INPUTS``, ``DESCRIBE_DEPENDENCIES``,
or ``DESCRIBE`` and the pipeline yields that metadata instead of executing the
``flow``.

Performance and memory
----------------------

Keep the following execution boundaries explicit:

- A pipeline instance is single-use. Rebuild it for another run.
- Most item ``transformers`` are iterator-oriented, but ``write``, ``split``,
  ``sort``, ``reverse``, ``count``, and a grouping ``sum`` hold the whole
  ``stream`` in memory, so none of them can run on an unbounded source. See the
  `FAQ`_ for the full table of what each retains.
- ``SyncPipe(parallel=True)`` currently materializes the ``pipe`` ``source`` before
  local thread or process mapping. Don't use it for an unbounded ``stream``.
- ``AsyncPipe(parallel=True)`` uses bounded concurrency and backpressure for
  loopable ``pipes``. Tune ``connections`` first; increase ``prefetch`` only when
  buffering improves throughput without violating memory limits.
- Parallel execution is unordered by default. Ordering can reduce throughput
  when an early item is slow.
- Awaiting an ``AsyncPipe`` materializes all remaining ``items``. Prefer
  ``async for`` when streaming behavior matters.
- ``split`` copies a fully materialized finite ``stream``. Prefer named
  ``publish``/``subscribe`` channels for lazy fan-out.
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
.. _riko-example-ext: ../examples/riko-example-ext
.. _register_module.py: ../examples/register_module.py
.. _register_alias.py: ../examples/register_alias.py
.. _Design Principles: ../README.rst#design-principles
.. _class based flows: ../README.rst#synchronous-processing
.. _DAG format doc: DAG_FORMAT.rst
