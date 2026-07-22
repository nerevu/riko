riko: A stream processing engine modeled after Yahoo! Pipes
===========================================================

Index
-----

`Introduction`_ | `Requirements`_ | `Word Count`_ | `Motivation`_ | `Usage`_ |
`Installation`_ | `Design Principles`_ | `Scripts`_ | `Command-line Interface`_ |
`Contributing`_ | `Credits`_ | `More Info`_ | `Project Structure`_ | `License`_

Introduction
------------

**riko** is a pure Python `library`_ for analyzing and processing ``streams`` of
structured data. ``riko`` has `synchronous`_ and `asynchronous`_ APIs, supports `parallel
execution`_, and is well suited for processing RSS feeds [#]_. ``riko`` also supplies
a `command-line interface`_ for executing ``flows``, i.e., stream processors aka ``workflows``.

With ``riko``, you can

- Read csv/xml/json/html files
- Create text and data based ``flows`` via modular `pipes`_
- Parse, extract, and process RSS/Atom feeds
- Create awesome mashups [#]_, APIs, and maps
- Perform `parallel processing`_ via cpus/processors or threads
- and much more...

Notes
^^^^^

.. [#] `Really Simple Syndication`_
.. [#] `Mashup (web application hybrid)`_

Requirements
------------

``riko`` has been tested and is known to work on Python 3.7, 3.8, and 3.9; and PyPy3.7.

Optional Dependencies
^^^^^^^^^^^^^^^^^^^^^

========================  ===================  ===========================
Feature                   Dependency           Installation
========================  ===================  ===========================
Async API                 `Twisted`_           ``pip install riko[async]``
Accelerated xml parsing   `lxml`_ [#]_         ``pip install riko[perf]``
Accelerated feed parsing  `speedparser`_ [#]_  ``pip install riko[perf]``
========================  ===================  ===========================

Notes
^^^^^

.. [#] If ``lxml`` isn't present, ``riko`` will default to the builtin Python xml parser
.. [#] If ``speedparser`` isn't present, ``riko`` will default to ``feedparser``

Word Count
----------

In this example, we use several `pipes`_ to count the words on a webpage.

.. code-block:: python

    >>> ### Create a SyncPipe flow ###
    >>> #
    >>> # `SyncPipe` is a convenience class that creates chainable flows
    >>> # and allows for parallel processing.
    >>> from riko import get_path
    >>> from riko.collections import SyncPipe
    >>>
    >>> ### Set the pipe configurations ###
    >>> #
    >>> # Notes:
    >>> #   1. the `detag` option will strip all html tags from the result
    >>> #   2. fetch the text contained inside the 'body' tag of a web page
    >>> #      (`get_path` looks up a cached copy in the `data` directory)
    >>> #   3. replace newlines with spaces and assign the result to 'content'
    >>> #   4. tokenize the resulting text using whitespace as the delimeter
    >>> #   5. count the number of times each token appears
    >>> #   6. extract the first word and its count
    >>> #   7. extract the second word and its count
    >>> #   8. extract the third word and its count
    >>> url = get_path('users.jyu.fi.html')
    >>> fetch_conf = {
    ...     'url': url, 'start': '<body>', 'end': '</body>', 'detag': True}  # 1
    >>>
    >>> replace_conf = {
    ...     'rule': [
    ...         {'find': '\r\n', 'replace': ' '},
    ...         {'find': '\n', 'replace': ' '}]}
    >>>
    >>> flow = (
    ...     SyncPipe('fetchpage', conf=fetch_conf)                           # 2
    ...         .strreplace(conf=replace_conf, assign='content')             # 3
    ...         .tokenizer(conf={'delimiter': ' '}, emit=True)               # 4
    ...         .count(conf={'count_key': 'content'}))                       # 5
    >>>
    >>> next(flow)                                                           # 6
    {'Tidy': 1}
    >>> next(flow)                                                           # 7
    {'your': 1}
    >>> next(flow)                                                           # 8
    {'HTML': 1}

Motivation
----------

Why I built riko
^^^^^^^^^^^^^^^^

Yahoo! Pipes [#]_ was a user friendly web application used to

  aggregate, manipulate, and mashup content from around the web

Wanting to create custom pipes, I came across `pipe2py`_ which translated a
Yahoo! Pipe into python code. ``pipe2py`` suited my needs at the time
but was unmaintained and lacked asynchronous or parallel processing.

``riko`` addresses the shortcomings of ``pipe2py`` and contains ~ `50 built-in`_
modules, aka ``pipes``, that allow you to programmatically perform most of the
tasks Yahoo! Pipes allowed.

Why you should use riko
^^^^^^^^^^^^^^^^^^^^^^^

``riko`` provides a number of benefits / differences from other stream processing
applications such as Huginn, Flink, Spark, and Storm [#]_. Namely:

- a small footprint (CPU and memory usage)
- native RSS/Atom support
- simple installation and usage
- a pure python library with `pypy`_ support
- builtin modular ``pipes`` to filter, sort, and modify ``streams``

The subsequent tradeoffs ``riko`` makes are:

- not distributed (able to run on a cluster of servers)
- no GUI for creating ``flows``
- doesn't continually monitor ``streams`` for new data
- can't react to specific events
- iterator (pull) based so streams only support a single consumer [#]_

The following table summarizes these observations:

=======  ===========  =========  =====  ===========  =====  ========  ========  ===========
library  Stream Type  Footprint  RSS    simple [#]_  async  parallel  CEP [#]_  distributed
=======  ===========  =========  =====  ===========  =====  ========  ========  ===========
riko     pull/push    small      √      √            √      √
pipe2py  pull         small      √      √
Huginn   push         med        √                   [#]_   √         √
Others   push         large      [#]_   [#]_         [#]_   √         √         √
=======  ===========  =========  =====  ===========  =====  ========  ========  ===========

For more detailed information, please check-out the `FAQ`_.

Notes
^^^^^

.. [#] Yahoo discontinued Yahoo! Pipes in 2015, but you can view what `remains`_
.. [#] `Huginn`_, `Flink`_, `Spark`_, and `Storm`_
.. [#] You can mitigate this via the `split`_ module
.. [#] Doesn't depend on outside services like MySQL, Kafka, YARN, ZooKeeper, or Mesos
.. [#] `Complex Event Processing`_
.. [#] Huginn doesn't appear to make `async web requests`_
.. [#] Many libraries can't parse RSS streams without the use of 3rd party libraries
.. [#] While most libraries offer a local mode, many require integrating with a data ingestor (e.g., Flume/Kafka) to do anything useful
.. [#] I can't find evidence that these libraries offer an async APIs (and apparently `Spark doesn't`_)

Usage
-----

``riko`` is intended to be used either directly as a Python library or in the console
the via `runpipe` CLI.

Usage Index
^^^^^^^^^^^

- `Fetching feeds`_
- `Synchronous processing`_
- `Parallel processing`_
- `Asynchronous processing`_
- `Fan-out (pubsub)`_
- `Cookbook`_

Fetching feeds
^^^^^^^^^^^^^^

``riko`` can fetch rss feeds from both local and remote filepaths via "source"
``pipes``. Each "source" ``pipe`` returns a ``stream``, i.e., an iterator of
dictionaries, aka ``items``.

.. code-block:: python

    >>> from riko import get_path
    >>> from riko.modules.fetch import pipe as fetch
    >>> from riko.modules.fetchsitefeed import pipe as fetchsitefeed
    >>>
    >>> # Note: `get_path` looks up a cached copy of a url in the `data`
    >>> # directory, so these examples run offline
    >>>
    >>> ### Fetch the first RSS feed found on a web page ###
    >>> stream = fetchsitefeed(conf={'url': get_path('cnn.html')})
    >>>
    >>> ### Fetch an RSS feed ###
    >>> stream = fetch(conf={'url': get_path('feed.xml')})
    >>>
    >>> ### View the fetched RSS feed(s) ###
    >>> #
    >>> # Note: regardless of how you fetch an RSS feed, it will have the same
    >>> # structure
    >>> item = next(stream)
    >>> sorted(item)
    ['author', 'author_detail', 'authors', 'comments', 'content', 'dc:creator', 'description', 'id', 'link', 'links', 'pubDate', 'published', 'published_parsed', 'summary', 'tags', 'title', 'updated_parsed', 'y:id', 'y:published', 'y:title']
    >>> item['title'], item['author'], item['id']
    ('Donations', {'name': 'WriteToReply', 'uri': None}, 'http://writetoreply.org/?page_id=111')

Please see the `FAQ`_ for a complete list of supported `file types`_ and
`protocols`_. Please see `Fetching data and feeds`_ for more examples.

Synchronous processing
^^^^^^^^^^^^^^^^^^^^^^

``riko`` can modify ``streams`` via the `50 built-in`_ ``pipes``

.. code-block:: python

    >>> from riko import get_path
    >>> from riko.collections import SyncPipe
    >>>
    >>> ### Set the pipe configurations ###
    >>> fetch_conf = {'url': get_path('feed.xml')}
    >>> filter_rule = {'field': 'title', 'op': 'contains', 'value': 'a'}
    >>>
    >>> ### Create a SyncPipe flow ###
    >>> #
    >>> # `SyncPipe` is a convenience class that creates chainable flows
    >>> # and allows for parallel processing.
    >>> #
    >>> # The following flow will:
    >>> #   1. fetch a (cached) RSS feed
    >>> #   2. filter for items with an 'a' in the title
    >>> #   3. sort the items ascending by title
    >>> #
    >>> # Note: sorting is not lazy so take caution when using this pipe
    >>>
    >>> flow = (
    ...     SyncPipe('fetch', conf=fetch_conf)               # 1
    ...         .filter(conf={'rule': filter_rule})          # 2
    ...         .sort(conf={'rule': {'field': 'title'}}))    # 3
    >>>
    >>> next(flow)['title']                                  # 4
    'Donations'

Please see `alternate workflow creation`_ for an alternative (function based) method for
creating a ``stream``. Please see `pipes`_ for a complete list of available ``pipes``.

Parallel processing
^^^^^^^^^^^^^^^^^^^

An example using ``riko``'s parallel API to spawn a ``ThreadPool`` [#]_

.. code-block:: python

    >>> from riko import get_path
    >>> from riko.collections import SyncPipe
    >>>
    >>> ### Set the pipe configurations ###
    >>> fetch_conf = {'url': get_path('feed.xml')}
    >>> filter_rule = {'field': 'title', 'op': 'contains', 'value': 'a'}
    >>>
    >>> ### Create a parallel SyncPipe flow ###
    >>> #
    >>> # The following flow will:
    >>> #   1. fetch a (cached) RSS feed
    >>> #   2. filter for items with an 'a' in the title, in parallel (4 workers)
    >>> #
    >>> # Note: no point in sorting after the filter since parallel fetching doesn't guarantee
    >>> # order
    >>> flow = (
    ...     SyncPipe('fetch', conf=fetch_conf, parallel=True, workers=4)  # 1
    ...         .filter(conf={'rule': filter_rule}))                      # 2
    >>>
    >>> sorted(item['title'] for item in flow)                            # 3
    ['Donations', 'FAQ', 'General Comments', 'Notice & Takedown Policy', 'What’s it all about?']

Asynchronous processing
^^^^^^^^^^^^^^^^^^^^^^^

To enable asynchronous processing, you must install the ``async`` extra.

.. code-block:: bash

    pip install riko[async]

An example using ``riko``'s asynchronous API.

.. code-block:: python

    >>> from riko import get_path
    >>> from riko.bado import react, _issync
    >>> from riko.bado.mock import FakeReactor
    >>> from riko.collections import AsyncPipe
    >>>
    >>> ### Set the pipe configurations ###
    >>> fetch_conf = {'url': get_path('feed.xml')}
    >>> filter_rule = {'field': 'title', 'op': 'contains', 'value': 'a'}
    >>>
    >>> ### Create an AsyncPipe flow ###
    >>> #
    >>> # The following flow will:
    >>> #   1. fetch a (cached) RSS feed
    >>> #   2. filter for items with an 'a' in the title
    >>> #   3. extract the first item's title
    >>> async def run(reactor):
    ...     stream = await (
    ...         AsyncPipe('fetch', conf=fetch_conf)                 # 1
    ...             .filter(conf={'rule': filter_rule}))            # 2
    ...     print(next(stream)['title'])                            # 3
    >>>
    >>> if _issync:
    ...     print('Donations')
    ... else:
    ...     try:
    ...         react(run, _reactor=FakeReactor())
    ...     except SystemExit:
    ...         pass
    Donations

Discovering modules
^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from riko.collections import list_targets
    from riko.modules import list_modules

    # All modules
    list_modules()

    # All operators (broad, by decorator type)
    list_modules(type='operator')

    # All modules that support aggregation
    list_modules(subtype='aggregator')

    # Only modules whose default behavior is aggregation
    list_modules(subtype='aggregator', primary=True)

    # Full metadata for every module
    list_modules(show_metadata=True)

    # Available export targets (includes 'ofx'/'qif' only when csv2ofx is installed)
    list_targets()

Semantics:

- ``type`` filters by decorator type (``operator``, ``processor``, ``splitter``).
- ``subtype`` filters against ``supported_subtypes``.
- ``type`` and ``subtype`` are mutually exclusive — a subtype already implies its type.
- ``subtype`` in the metadata is the module's default behavior.
- ``supported_subtypes`` includes behaviors reachable through options such as ``emit=True``.
- Pass ``primary=True`` to match only the module's default subtype; ``primary=True`` requires ``subtype``.
- Module authors do not declare metadata attributes; it is derived from the decorator type, options, return annotation, and module name.

Cookbook
^^^^^^^^

Please see the `cookbook`_ or `ipython notebook`_ for more examples.

Notes
^^^^^

.. [#] You can instead enable a ``ProcessPool`` by additionally passing ``threads=False`` to ``SyncPipe``, i.e., ``SyncPipe('fetch', conf={'url': url}, parallel=True, threads=False)``.

Installation
------------

(You are using a `virtualenv`_, right?)

At the command line, install ``riko`` using either ``pip`` (*recommended*)

.. code-block:: bash

    pip install riko

or ``easy_install``

.. code-block:: bash

    easy_install riko

Please see the `installation doc`_ for more details.

Design Principles
-----------------

The primary data structures in ``riko`` are the ``item`` and ``stream``. An ``item``
is just a python dictionary, and a ``stream`` is an iterator of ``items``. You can
create a ``stream`` manually with something as simple as
``[{'content': 'hello world'}]``. You manipulate ``streams`` in
``riko`` via ``pipes``. A ``pipe`` is simply a function that accepts either a
``stream`` or ``item``, and returns a ``stream``. ``pipes`` are composable: you
can use the output of one ``pipe`` as the input to another ``pipe``.

``riko`` ``pipes`` come in two flavors; ``operators`` and ``processors``.
``operators`` operate on an entire ``stream`` at once and are unable to handle
individual items. Example ``operators`` include ``count``, ``filter``,
and ``reverse``.

.. code-block:: python

    >>> from riko.modules.reverse import pipe
    >>>
    >>> stream = [{'title': 'riko pt. 1'}, {'title': 'riko pt. 2'}]
    >>> next(pipe(stream))
    {'title': 'riko pt. 2'}

``processors`` process individual ``items`` and can be parallelized across
threads or processes. Example ``processors`` include ``fetchsitefeed``,
``hash``, ``itembuilder``, and ``regex``.

.. code-block:: python

    >>> from riko.modules.hash import pipe
    >>>
    >>> item = {'title': 'riko pt. 1'}
    >>> result = next(pipe(item, field='title'))
    >>> sorted(result)
    ['hash', 'title']
    >>> isinstance(result['hash'], int)
    True

Some ``processors``, e.g., ``tokenizer``, return multiple results.

.. code-block:: python

    >>> from riko.modules.tokenizer import pipe
    >>>
    >>> item = {'title': 'riko pt. 1'}
    >>> tokenizer_conf = {'delimiter': ' '}
    >>> stream = pipe(item, conf=tokenizer_conf, field='title')
    >>> list(stream)
    [{'content': 'riko'}, {'content': 'pt.'}, {'content': '1'}]

``operators`` are split into sub-types of ``aggregators``
and ``composers``. ``aggregators``, e.g., ``count``, combine
all ``items`` of an input ``stream`` into a new ``stream`` with a single ``item``;
while ``composers``, e.g., ``filter``, create a new ``stream`` containing
some or all ``items`` of an input ``stream``.

.. code-block:: python

    >>> from riko.modules.count import pipe
    >>>
    >>> stream = [{'title': 'riko pt 1'}, {'title': 'riko pt 2'}]
    >>> next(pipe(stream))
    {'count': 2}

In case you are confused from the "Word Count" example up top, ``count`` can return
multiple items if you pass in the ``count_key`` config option.

.. code-block:: python

    >>> counted = pipe(stream, conf={'count_key': 'title'})
    >>> next(counted)
    {'riko pt 1': 1}
    >>> next(counted)
    {'riko pt 2': 1}

``processors`` are split into sub-types of ``source`` and ``transformer``.
``sources``, e.g., ``itembuilder``, can create a ``stream`` while
``transformers``, e.g. ``hash`` can only transform items in a ``stream``.

.. code-block:: python

    >>> from riko.modules.itembuilder import pipe
    >>>
    >>> attrs = {'key': 'title', 'value': 'riko pt. 1'}
    >>> next(pipe(conf={'attrs': attrs}))
    {'title': 'riko pt. 1'}

The following table summaries these observations:

+-----------+-------------+--------+-------------+-----------------+------------------+
| type      | sub-type    | input  | output      | parallelizable? | creates streams? |
+-----------+-------------+--------+-------------+-----------------+------------------+
| operator  | aggregator  | stream | stream [#]_ |                 |                  |
|           +-------------+--------+-------------+-----------------+------------------+
|           | composer    | stream | stream      |                 |                  |
+-----------+-------------+--------+-------------+-----------------+------------------+
| processor | source      | item   | stream      | √               | √                |
|           +-------------+--------+-------------+-----------------+------------------+
|           | transformer | item   | stream      | √               |                  |
+-----------+-------------+--------+-------------+-----------------+------------------+

If you are unsure of the type of ``pipe`` you have, check its metadata.

.. code-block:: python

    >>> from riko.modules import fetchpage, count
    >>>
    >>> fetchpage.async_pipe.name, fetchpage.async_pipe.type, fetchpage.async_pipe.subtype
    ('fetchpage', 'processor', 'source')
    >>> count.pipe.name, count.pipe.type, count.pipe.subtype
    ('count', 'operator', 'aggregator')

The ``SyncPipe`` and ``AsyncPipe`` classes (among other things) perform this
check for you to allow for convenient method chaining and transparent
parallelization.

.. code-block:: python

    >>> from riko.collections import SyncPipe
    >>>
    >>> attrs = [
    ...     {'key': 'title', 'value': 'riko pt. 1'},
    ...     {'key': 'content', 'value': "Let's talk about riko!"}]
    >>> flow = SyncPipe('itembuilder', conf={'attrs': attrs}).hash()
    >>> item = next(flow)
    >>> item['title'], item['content'], isinstance(item['hash'], int)
    ('riko pt. 1', "Let's talk about riko!", True)

Please see the `cookbook`_ for advanced examples including how to wire in
vales from other pipes or accept user input.

Notes
^^^^^

.. [#] the output ``stream`` of an ``aggregator`` is an iterator of only 1 ``item``.

Fan-out (pubsub)
^^^^^^^^^^^^^^^^

Sometimes you need to consume the same ``stream`` from multiple independent pipelines.
For example, archiving every item while also sending urgent items, to an alert queue.
Consuming the iterator twice would exhaust it, and materialising it into a list defeats
lazy evaluation. ``riko`` solves this with the ``send`` and ``receive`` pipes.

- ``send`` is a transparent pass-through ``operator``: it yields every item
  unchanged while pushing a copy to one or more named channels.
- ``receive`` is an independent pull iterator that drains a named channel as items
  arrive.

Under the hood, each ``receive`` channel is a generator-based coroutine (the same
push pattern used by `ijson`_). ``send`` calls ``.send(item)`` on the primed
coroutine directly.

.. code-block:: python

    >>> from itertools import islice
    >>> from riko.modules.receive import pipe as receiver
    >>> from riko.modules.send import pipe as sender
    >>> from riko.utils import noop

    >>> ### Prime a named channel ###
    >>> alerts = receiver(conf={'name': 'alerts'}, func=noop)
    >>> next(alerts)
    {'state': <StreamState.PENDING: 1>}

    >>> ### items flow through AND are pushed to 'alerts' ###
    >>> stream = [{'title': 'Gravity paper', 'score': 42},
    ...           {'title': 'Breaking: riko 4.0', 'score': 980}]
    >>> source = sender(stream, others=['alerts'])

    >>> ### Consuming the sender drives the push ###
    >>> list(source)
    [{'title': 'Gravity paper', 'score': 42}, {'title': 'Breaking: riko 4.0', 'score': 980}]

    >>> ### Drain the alerts channel independently ###
    >>> #
    >>> # Note: an idle channel yields a `PENDING` state marker, so filter for
    >>> # real items when draining
    >>> [item for item in islice(alerts, 5) if 'state' not in item]
    [{'title': 'Gravity paper', 'score': 42}, {'title': 'Breaking: riko 4.0', 'score': 980}]

``send`` composes naturally in a ``SyncPipe`` chain via ``.send(others=[...])``.
The stream continues down the main pipeline while a copy flows to each named
receiver:

.. code-block:: python

    >>> from itertools import islice
    >>> from riko.collections import SyncPipe
    >>> from riko.modules.receive import pipe as receiver
    >>> from riko.utils import noop
    >>>
    >>> ### `archive` and `notify` stand in for your real side effects ###
    >>> #
    >>> # Note: a receiver `func` also sees `PENDING` state markers, so guard for
    >>> # the field you care about
    >>> archived, notified = [], []
    >>> archive = lambda item: archived.append(item['title']) if 'title' in item else None
    >>> notify = lambda item: notified.append(item['title']) if 'title' in item else None
    >>>
    >>> ### Prime two named channels ###
    >>> everything = receiver(conf={'name': 'everything'}, func=archive)
    >>> next(everything)
    {'state': <StreamState.PENDING: 1>}
    >>> breaking = receiver(conf={'name': 'breaking'}, func=notify)
    >>> next(breaking)
    {'state': <StreamState.PENDING: 1>}
    >>>
    >>> items = [
    ...     {'title': 'quiet', 'score': 42},
    ...     {'title': 'breaking: riko 4.0', 'score': 980},
    ...     {'title': 'also big', 'score': 750}]
    >>>
    >>> ### Send ALL items to 'everything' and filter, then send matches to 'breaking' ###
    >>> flow = (
    ...     SyncPipe(source=items)
    ...         .send(others=['everything'])
    ...         .filter(conf={'rule': [{'field': 'score', 'value': 500, 'op': 'greater'}]})
    ...         .send(others=['breaking'])
    ...         .sort(conf={'rule': [{'field': 'score'}]}))
    >>>
    >>> ### Consume the main pipeline (this also drives the pushes) ###
    >>> [item['title'] for item in flow]  # sorted high score items
    ['also big', 'breaking: riko 4.0']
    >>>
    >>> ### Drain each channel: each `func` runs as items arrive ###
    >>> _ = list(islice(everything, 5))
    >>> archived  # all items in original order
    ['quiet', 'breaking: riko 4.0', 'also big']
    >>> _ = list(islice(breaking, 5))
    >>> notified  # high score items in original order
    ['breaking: riko 4.0', 'also big']

Multiple receivers can listen on different channels from the same ``send`` call by
passing additional names to ``others``:

.. code-block:: python

    source = sender(stream, others=['breaking', 'archive', 'metrics'])

Each channel is drained independently; draining one does not affect the others.

``split`` vs ``send``/``receive``
''''''''''''''''''''''''''''''''''

``riko`` also has a ``split`` pipe that copies a stream for multiple consumers:

.. code-block:: python

    >>> from riko.modules.split import pipe as split
    >>>
    >>> items = [{'title': 'riko pt. 1'}, {'title': 'riko pt. 2'}]
    >>> stream1, stream2 = split(items)
    >>> next(stream1)
    {'title': 'riko pt. 1'}
    >>> next(stream2)
    {'title': 'riko pt. 1'}

The difference between them is that ``split`` calls ``list(stream)`` internally, so it
**eagerly materialises** the entire stream into memory before handing out copies.
``send``/``receive`` are **lazy**: each item is pushed to receivers as it passes
through, with no upfront buffering.

+-------------------------------+---------------------------+----------------------------+
| Dimension                     | ``split``                 | ``send`` / ``receive``     |
+===============================+===========================+============================+
| Evaluation                    | Eager — full stream in    | Lazy — one item at a time  |
|                               | memory before any copy    |                            |
+-------------------------------+---------------------------+----------------------------+
| Memory                        | O(n × copies)             | O(queue size, default 256) |
+-------------------------------+---------------------------+----------------------------+
| Infinite / very large streams | Hangs or OOM              | Works                      |
+-------------------------------+---------------------------+----------------------------+
| API                           | Returns N iterators       | Receivers primed upfront;  |
|                               | in one call               | drained independently      |
+-------------------------------+---------------------------+----------------------------+
| Transform per branch          | No — identical copies     | Yes — ``func=`` in each    |
|                               |                           | ``receive``                |
+-------------------------------+---------------------------+----------------------------+
| SyncPipe chain                | Returns N streams;        | ``.send(others=[...])``    |
|                               | not chainable             | stays in the chain         |
+-------------------------------+---------------------------+----------------------------+

**Use** ``split`` when the stream is small and finite and you want the simplest
possible API.

**Use** ``send``/``receive`` when the stream is large, potentially infinite, or
when the main pipeline must stay lazy (e.g., inside a ``timeout`` or ``truncate``
composer). ``receive`` also lets you apply a different transform (``func``)
to the branched items without touching the main flow.

.. _ijson: https://github.com/ICRAR/ijson/blob/master/notes/design_notes.rst

Command-line Interface
----------------------

``riko`` provides a command, ``runpipe``, to execute ``workflows``. A
``workflow`` is simply a file containing a function named ``pipe`` that creates
a ``flow`` and processes the resulting ``stream``.

CLI Usage
^^^^^^^^^

  usage: runpipe [pipeid]

  description: Runs a riko pipe

  positional arguments:
    pipeid       The pipe to run (default: reads from stdin).

  optional arguments:
    -h, --help   show this help message and exit
    -a, --async  Load async pipe.

    -t, --test   Run in test mode (uses default inputs).

CLI Setup
^^^^^^^^^

``flow.py``

.. code-block:: python

    from riko.collections import SyncPipe

    conf1 = {'attrs': [{'value': 'https://google.com', 'key': 'content'}]}
    conf2 = {'rule': [{'find': 'com', 'replace': 'co.uk'}]}

    def pipe(test=False):
        kwargs = {'conf': conf1, 'test': test}
        flow = SyncPipe('itembuilder', **kwargs).strreplace(conf=conf2)

        for i in flow:
            print(i)

CLI Examples
^^^^^^^^^^^^

Now to execute ``flow.py``, type the command ``runpipe flow``. You should
then see the following output in your terminal:

.. code-block:: bash

    https://google.co.uk

``runpipe`` will also search the ``examples`` directory for ``workflows``. Type
``runpipe demo`` and you should see the following output:

.. code-block:: bash

    Deadline to clear up health law eligibility near 682

Compiling workflows
^^^^^^^^^^^^^^^^^^^^

``riko`` also ships two commands for working with JSON pipe definitions (the
Yahoo! Pipes-style ``{"modules": [...], "wires": [...]}`` format):

- ``compile`` translates a JSON pipe definition into a runnable Python module.
- ``convert_dag`` expands a *bare-bones DAG* into a full JSON pipe definition.

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

Chaining the two commands turns a DAG straight into runnable Python (both write
to stdout, or to a file via ``-o``):

.. code-block:: bash

    convert_dag flow.dag.json -o flow.json
    compile flow.json -o flow.py

See `docs/DAG_FORMAT.md`_ for the full format and expansion rules.

Scripts
-------

``riko`` comes with a built in task manager ``manage``.

Setup
^^^^^

.. code-block:: bash

    pip install riko[develop]

Examples
^^^^^^^^

*Run python linter and nose tests*

.. code-block:: bash

    manage lint
    manage test

Contributing
------------

Please mimic the coding style/conventions used in this repo.
If you add new classes or functions, please add the appropriate doc blocks with
examples. Also, make sure the python linter and nose tests pass.

Please see the `contributing doc`_ for more details.

Credits
-------

Shoutout to `pipe2py`_ for heavily inspiring ``riko``. ``riko`` started out as a fork
of ``pipe2py``, but has since diverged so much that little (if any) of the original
code-base remains.

More Info
---------

- `FAQ`_
- `Cookbook`_
- `iPython Notebook`_
- `Step-by-Step Intro. Tutorial`_

Project Structure
-----------------

.. code-block:: bash

    ┌── bin
    │   └── bench
    ├── docs
    │   ├── AUTHORS.rst
    │   ├── CHANGES.rst
    │   ├── COOKBOOK.rst
    │   ├── DAG_FORMAT.md
    │   ├── FAQ.rst
    │   ├── INSTALLATION.rst
    │   └── *.md              (design/roadmap notes)
    ├── examples/*
    ├── riko
    │   ├── __init__.py
    │   ├── autorss.py
    │   ├── cast.py
    │   ├── collections.py    (SyncPipe, AsyncPipe, SyncCollection, AsyncCollection)
    │   ├── compile.py        (JSON pipe → executable pipeline / Python module)
    │   ├── currencies.py
    │   ├── dates.py
    │   ├── dotdict.py
    │   ├── exceptions.py
    │   ├── helpers.py
    │   ├── locations.py
    │   ├── parsers.py
    │   ├── pprint2.py
    │   ├── topsort.py
    │   ├── utils.py
    │   ├── bado             (async backend: __init__, io, itertools, mock, util)
    │   ├── cli              (manage, runpipe, benchmark, compile, convert_dag)
    │   ├── data/*
    │   ├── modules/*        (the built-in pipes)
    │   ├── templates/*      (codegen Jinja templates)
    │   └── types            (compile, general, modules, values)
    ├── tests
    │   ├── __init__.py
    │   ├── conftest.py
    │   ├── dags/*           (bare-bones DAG fixtures)
    │   ├── pipelines/*      (JSON pipe definitions)
    │   ├── pypipelines/*    (expected generated Python modules)
    │   └── test_*.py
    ├── CLAUDE.md
    ├── conftest.py
    ├── CONTRIBUTING.rst
    ├── LICENSE
    ├── pyproject.toml
    ├── README.rst
    ├── tox.ini
    └── uv.lock

License
-------

``riko`` is distributed under the `MIT License`_.

.. _synchronous: #synchronous-processing
.. _asynchronous: #asynchronous-processing
.. _parallel execution: #parallel-processing
.. _parallel processing: #parallel-processing
.. _library: #usage

.. _contributing doc: https://github.com/nerevu/riko/blob/master/CONTRIBUTING.rst
.. _docs/DAG_FORMAT.md: https://github.com/nerevu/riko/blob/master/docs/DAG_FORMAT.md
.. _FAQ: https://github.com/nerevu/riko/blob/master/docs/FAQ.rst
.. _pipes: https://github.com/nerevu/riko/blob/master/docs/FAQ.rst#what-pipes-are-available
.. _50 built-in: https://github.com/nerevu/riko/blob/master/docs/FAQ.rst#what-pipes-are-available
.. _file types: https://github.com/nerevu/riko/blob/master/docs/FAQ.rst#what-file-types-are-supported
.. _protocols: https://github.com/nerevu/riko/blob/master/docs/FAQ.rst#what-protocols-are-supported
.. _installation doc: https://github.com/nerevu/riko/blob/master/docs/INSTALLATION.rst
.. _Cookbook: https://github.com/nerevu/riko/blob/master/docs/COOKBOOK.rst
.. _split: https://github.com/nerevu/riko/blob/master/riko/modules/split.py#L15-L18
.. _alternate workflow creation: https://github.com/nerevu/riko/blob/master/docs/COOKBOOK.rst#alternate-workflow-creation
.. _Fetching data and feeds: https://github.com/nerevu/riko/blob/master/docs/COOKBOOK.rst#fetching-data-and-feeds

.. _pypy: http://pypy.org
.. _Really Simple Syndication: https://en.wikipedia.org/wiki/RSS
.. _Mashup (web application hybrid): https://en.wikipedia.org/wiki/Mashup_%28web_application_hybrid%29
.. _pipe2py: https://github.com/ggaughan/pipe2py/
.. _Huginn: https://github.com/cantino/huginn/
.. _Flink: http://flink.apache.org/
.. _Spark: http://spark.apache.org/streaming/
.. _Storm: http://storm.apache.org/
.. _Complex Event Processing: https://en.wikipedia.org/wiki/Complex_event_processing
.. _async web requests: https://github.com/cantino/huginn/blob/bf7c2feba4a7f27f39de96877c121d40282c0af9/app/models/agents/rss_agent.rb#L101
.. _Spark doesn't: https://github.com/perwendel/spark/issues/208
.. _remains: https://web.archive.org/web/20150930021241/http://pipes.yahoo.com/pipes/
.. _lxml: http://www.crummy.com/software/BeautifulSoup/bs4/doc/#installing-a-parser
.. _Twisted: http://twistedmatrix.com/
.. _speedparser: https://github.com/jmoiron/speedparser
.. _MIT License: http://opensource.org/licenses/MIT
.. _virtualenv: http://www.virtualenv.org/en/latest/index.html
.. _iPython Notebook: http://nbviewer.jupyter.org/github/nerevu/riko/blob/master/examples/usage.ipynb
.. _Step-by-Step Intro. Tutorial: http://nbviewer.jupyter.org/github/aemreunal/riko-tutorial/blob/master/Tutorial.ipynb
