riko Cookbook
=============

Index
-----

`User input`_ | `Fetching data and feeds`_ | `Alternate conf value entry`_ | `Alternate workflow creation`_ | `Managing pipeline lifecycle`_ | `Exporting results`_ | `Asynchronous workflows`_ | `Compiling JSON workflows`_ | `Inspecting a workflow`_

User input
----------

Some workflows require user input (via the ``pipeinput`` pipe). By default,
``pipeinput`` prompts the user via the console, but in some situations this may
not be appropriate, e.g., testing or integrating with a website. In such cases,
the input values can instead be read from the workflow's ``inputs`` kwargs (a
set of values passed into every pipe).

.. code-block:: python

    >>> from riko.modules.input import pipe
    >>> conf = {'prompt': 'How old are you?', 'type': 'int'}
    >>> next(pipe(conf=conf, inputs={'content': '30'}))
    30

Fetching data and feeds
-----------------------

``riko`` can read both local and remote filepaths via ``source`` pipes. All ``source``
pipes return an equivalent ``feed`` iterator of dictionaries,
aka ``items``.

.. code-block:: python

    >>> from itertools import chain
    >>> from riko import get_path
    >>> from riko.modules.fetch import pipe as fetch
    >>> from riko.modules.fetchpage import pipe as fetchpage
    >>> from riko.modules.fetchdata import pipe as fetchdata
    >>> from riko.modules.fetchsitefeed import pipe as fetchsitefeed
    >>> from riko.modules.feedautodiscovery import pipe as feedautodiscovery
    >>>
    >>> # Note: `get_path` looks up a cached copy of a url in the `data`
    >>> # directory, so these examples run offline
    >>>
    >>> ### Fetch a web page ###
    >>> stream = fetchpage(conf={'url': get_path('users.jyu.fi.html')})
    >>>
    >>> ### Fetch a data file ###
    >>> stream = fetchdata(conf={'url': get_path('quote.json')})
    >>>
    >>> ### View the fetched data ###
    >>> item = next(stream)
    >>> item['base']
    'USD'

    >>> ### Fetch an rss feed ###
    >>> stream = fetch(conf={'url': get_path('feed.xml')})
    >>>
    >>> ### Fetch the first rss feed found on a page ###
    >>> stream = fetchsitefeed(conf={'url': get_path('cnn.html')})
    >>>
    >>> ### Find all rss links on a page and fetch the feeds ###
    >>> entries = feedautodiscovery(conf={'url': get_path('bbc.html')})
    >>> urls = [entry['link'] for entry in entries]
    >>> urls
    ['file://riko/data/bbci.co.uk.xml']
    >>> stream = chain.from_iterable(fetch(conf={'url': url}) for url in urls)
    >>>
    >>> ### Alternatively, create a SyncCollection ###
    >>> #
    >>> # `SyncCollection` is a url fetching convenience class with support for
    >>> # parallel processing
    >>> from riko.collections import SyncCollection
    >>>
    >>> sources = [{'url': url} for url in urls]
    >>> stream = SyncCollection(sources)
    >>>
    >>> ### View the fetched rss feed(s) ###
    >>> #
    >>> # Note: regardless of how you fetch an rss feed, it will have the same
    >>> # structure
    >>> next(stream)['title']
    "EU sets out 'phased' Brexit strategy"


Alternate ``conf`` value entry
------------------------------

Some workflows have ``conf`` values that are wired from other pipes

.. code-block:: python

    >>> from riko import get_path
    >>> from riko.modules.fetch import pipe
    >>>
    >>> conf = {'url': {'subkey': 'url'}}
    >>> result = pipe({'url': get_path('feed.xml')}, conf=conf)
    >>> item = next(result)
    >>> {'author', 'content', 'id', 'link', 'published', 'summary', 'title'} <= set(item)
    True

Alternate workflow creation
---------------------------

In addition to `class based workflows`_ ``riko`` supports a pure functional
style [#]_.

.. code-block:: python

    >>> import itertools as it
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
    >>> ### Create a workflow ###
    >>> #
    >>> # The following workflow will:
    >>> #   1. fetch the url and return the content between the body tags
    >>> #   2. replace newlines with spaces
    >>> #   3. tokenize (split) the content by spaces, i.e., yield words
    >>> #   4. count the words
    >>> #
    >>> # Note: because `fetchpage` and `strreplace` each return an iterator of
    >>> # just one item, we can safely call `next` without fear of loosing data
    >>> page = next(fetchpage(conf=fetch_conf))
    >>> replaced = next(strreplace(page, conf=replace_conf, assign='content'))
    >>> words = tokenizer(replaced, conf={'delimiter': ' '}, emit=True)
    >>> counts = count(words)
    >>> next(counts)
    {'count': 70}

    >>> from itertools import chain
    >>> from riko import get_path
    >>> from riko.modules.fetch import pipe as fetch
    >>> from riko.modules.filter import pipe as _filter
    >>> from riko.modules.subelement import pipe as subelement
    >>> from riko.modules.regex import pipe as regex
    >>> from riko.modules.sort import pipe as _sort
    >>>
    >>> ### Set the pipe configurations ###
    >>> #
    >>> # Note: `get_path` just looks up files in the `data` directory to
    >>> # simplify testing
    >>> fetch_conf = {'url': get_path('feed.xml')}
    >>> filter_rule = {
    ...     'field': 'y:published', 'op': 'before', 'value': '2/5/09'}
    >>> sub_conf = {'path': 'content.value'}
    >>> match = r'(.*href=")([\w:/.@]+)(".*)'
    >>> regex_rule = {'field': 'content', 'match': match, 'replace': '$2'}
    >>> sort_conf = {'rule': {'field': 'content', 'dir': 'desc'}}
    >>>
    >>> ### Create a workflow ###
    >>> #
    >>> # The following workflow will:
    >>> #   1. fetch the rss feed
    >>> #   2. filter for items published before 2/5/2009
    >>> #   3. extract the path `content.value` from each feed item
    >>> #   4. replace the extracted text with the last href url contained
    >>> #      within it
    >>> #   5. reverse sort the items by the replaced url
    >>> #
    >>> # Note: sorting is not lazy so take caution when using this pipe
    >>> stream = fetch(conf=fetch_conf)
    >>> filtered = _filter(stream, conf={'rule': filter_rule})
    >>> extracted = (subelement(i, conf=sub_conf, emit=True) for i in filtered)
    >>> flat_extract = chain.from_iterable(extracted)
    >>> matched = (regex(i, conf={'rule': regex_rule}) for i in flat_extract)
    >>> flat_match = chain.from_iterable(matched)
    >>> sorted_match = _sort(flat_match, conf=sort_conf)
    >>> next(sorted_match)
    {'content': 'mailto:mail@writetoreply.org'}

Managing pipeline lifecycle
---------------------------

A ``SyncPipe``/``AsyncPipe`` (and the ``SyncCollection``/``AsyncCollection``
classes) represents a *single* execution. Iterating it consumes the underlying
``stream``; iterating again yields an empty ``stream`` rather than silently
re-running. You can inspect a pipe's state at any point via its read-only
``state``/``closed``/``exhausted``/``failed`` properties.

.. code-block:: python

    >>> from riko.collections import SyncPipe, PipeState
    >>>
    >>> flow = SyncPipe('hash', source=[{'content': 'a'}, {'content': 'b'}])
    >>> flow.state
    <PipeState.NEW: 'new'>
    >>> len(list(flow))                    # consume the stream
    2
    >>> flow.exhausted, flow.state
    (True, <PipeState.EXHAUSTED: 'exhausted'>)
    >>> list(flow)                         # re-iterating yields nothing
    []

Parallel pipes own a worker pool. Use the pipe as a context manager (or call
``close()``/``terminate()``) to release it deterministically — ``terminate`` runs
automatically if the ``with`` block exits via an exception.

.. code-block:: python

    >>> with SyncPipe('hash', source=[{'content': 'a'}], parallel=True) as flow:
    ...     results = list(flow)
    >>> flow.pool is None                  # pool released on exit
    True

Chaining onto a ``closed`` or ``failed`` pipe raises ``PipelineStateError`` (a
``NEW``, ``RUNNING``, or ``EXHAUSTED`` pipe still chains — chaining wraps whatever
of the source remains).

.. code-block:: python

    >>> from riko.exceptions import PipelineStateError
    >>>
    >>> flow = SyncPipe('hash', source=[{'content': 'a'}])
    >>> flow.close()
    >>> try:
    ...     flow.count()
    ... except PipelineStateError:
    ...     print('cannot chain a closed pipe')
    cannot chain a closed pipe

Exporting results
-----------------

A ``flow`` is a lazy, single-use iterator. ``export()`` materializes it into a
concrete list you can index, measure, and reuse.

.. code-block:: python

    >>> from riko.collections import SyncPipe
    >>>
    >>> flow = SyncPipe('hash', source=[{'title': 'a'}, {'title': 'b'}])
    >>> items = flow.export()
    >>> len(items)            # unlike the flow, the list can be measured...
    2
    >>> items[0]['title']     # ...and indexed / iterated repeatedly
    'a'

For serialized output, the top-level ``export`` converter writes ``items`` to a
string buffer (or to a file if you pass a path as the third argument, returning
the number of records written). ``list_targets()`` lists the available targets
(``ofx``/``qif`` require the optional ``csv2ofx`` dependency).

.. code-block:: python

    >>> from riko import export
    >>> from riko.collections import list_targets
    >>>
    >>> items = [{'title': 'a', 'score': 1}, {'title': 'b', 'score': 2}]
    >>> base_targets = {'csv', 'geojson', 'json', 'list', 'tuple'}
    >>>
    >>> export(items, 'json').getvalue()
    '[{"score": 1, "title": "a"}, {"score": 2, "title": "b"}]'
    >>> base_targets.issubset(list_targets())
    True

Asynchronous workflows
----------------------

The ``async`` extra (``pip install riko[async]``) enables ``AsyncPipe`` and
``AsyncCollection``, which mirror their synchronous counterparts. Build a ``flow``
the same way, then either ``await`` it (materializing the whole ``stream``) or
consume it lazily with ``async for``. ``riko.bado.run`` executes a coroutine on
the installed backend, and ``issync`` is ``True`` when no async backend is present
(so these examples degrade gracefully when the extra is absent).

Lazy async iteration
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    >>> from riko import get_path
    >>> from riko.bado import run, issync
    >>> from riko.collections import AsyncPipe
    >>>
    >>> fetch_conf = {'url': get_path('feed.xml')}
    >>> filter_rule = {'field': 'title', 'op': 'contains', 'value': 'a'}
    >>>
    >>> ### Consume an AsyncPipe item-by-item with `async for` ###
    >>> async def main():
    ...     pipe = (
    ...         AsyncPipe('fetch', conf=fetch_conf)
    ...             .filter(conf={'rule': filter_rule}))
    ...     titles = [item['title'] async for item in pipe]
    ...     print(titles[0], '/', len(titles))
    >>>
    >>> if issync:
    ...     print('Donations / 5')
    ... else:
    ...     run(main)
    Donations / 5

Fetching feeds concurrently
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``AsyncCollection`` is the async counterpart of ``SyncCollection``: it fetches
every source concurrently and merges them into a single ``stream``.

.. code-block:: python

    >>> from riko.collections import AsyncCollection
    >>>
    >>> async def main():
    ...     sources = [{'url': get_path('feed.xml')}, {'url': get_path('gawker.xml')}]
    ...     coll = AsyncCollection(sources)
    ...     print(len([item async for item in coll]))
    >>>
    >>> if issync:
    ...     print(32)
    ... else:
    ...     run(main)
    32

Bounded parallelism
^^^^^^^^^^^^^^^^^^^^

Passing ``parallel=True`` maps a stage over its source with bounded concurrency
and backpressure, so large or streaming sources are never materialized up front.
Pass ``ordered=True`` to preserve source order (the default is unordered — results
arrive as they complete) and ``connections`` to cap the number of in-flight items.

.. code-block:: python

    >>> async def main():
    ...     pipe = (
    ...         AsyncPipe(
    ...             'itembuilder',
    ...             conf={'attrs': {'key': 'content', 'value': 'a,bb,ccc'}},
    ...             parallel=True,
    ...             ordered=True)
    ...             .tokenizer(emit=True)
    ...             .hash())
    ...     print([item['content'] async for item in pipe])
    >>>
    >>> if issync:
    ...     print(['a', 'bb', 'ccc'])
    ... else:
    ...     run(main)
    ['a', 'bb', 'ccc']

Compiling JSON workflows
------------------------

In addition to writing ``workflows`` in Python, ``riko`` can load and compile
workflows stored as JSON pipe definitions (the Yahoo! Pipes-style
``{"modules": [...], "wires": [...]}`` format). The simplest way to author one is
as a *bare-bones DAG* — a list of ``modules`` plus optional ``[source, target]``
wire pairs. When ``wires`` are omitted the modules are chained linearly, and a
missing ``id`` defaults to ``sw-{n}``.

.. code-block:: python

    >>> from riko import Context
    >>> from riko.compile import convert_dag, build_pipeline, parse_pipe_def
    >>>
    >>> ### Author a terse, linear DAG (no wires, no ids) ###
    >>> dag = {
    ...     'modules': [
    ...         {'type': 'itembuilder', 'conf': {'attrs': {'key': 'greeting', 'value': 'hello'}}},
    ...         {'type': 'rename', 'conf': {'rule': {'field': 'greeting', 'newval': 'salutation'}}},
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
``compile`` CLI), use ``compile``:

.. code-block:: python

    >>> from riko.compile import compile
    >>> source = compile(pipe_def, 'pipe_demo')

Note that fan-in operators such as ``union``/``join`` cannot be expressed with the
``[source, target]`` pair format (their secondary inputs need ``_OTHER{n}``
targets) and must be authored as a full JSON pipe definition instead. See the
`DAG format doc`_ for the complete schema and expansion rules.

Inspecting a workflow
---------------------

You can introspect a JSON pipe definition *without running it*.
``extract_dependencies`` returns the sorted set of modules a workflow uses —
handy for validating that every required ``pipe`` is installed before execution.

.. code-block:: python

    >>> from riko.compile import convert_dag, extract_dependencies
    >>>
    >>> dag = {
    ...     'modules': [
    ...         {'type': 'itembuilder', 'conf': {'attrs': {'key': 'greeting', 'value': 'hi'}}},
    ...         {'type': 'rename', 'conf': {'rule': {'field': 'greeting', 'newval': 'salutation'}}},
    ...     ]
    ... }
    >>> extract_dependencies(convert_dag(dag))
    ['itembuilder', 'rename']

A *compiled* pipeline (see `Compiling JSON workflows`_) can additionally report
its input requirements or module dependencies at run time — pass a ``Context``
whose ``mode`` is ``ExecutionMode.DESCRIBE_INPUTS``, ``DESCRIBE_DEPENDENCIES``, or
``DESCRIBE`` and the pipeline yields that metadata instead of executing the flow.

Notes
^^^^^

.. [#] See `Design Principles`_ for explanation on `pipe` types and sub-types

.. _Design Principles: https://github.com/nerevu/riko/blob/master/README.rst#design-principles
.. _class based workflows: https://github.com/nerevu/riko/blob/master/README.rst#synchronous-processing
.. _DAG format doc: https://github.com/nerevu/riko/blob/master/docs/DAG_FORMAT.md
