riko: A stream processing framework modeled after Yahoo! Pipes
==============================================================

|travis| |versions| |pypi|

Index
-----

`Introduction`_ | `Requirements`_ | `Word Count`_ | `Motivation`_ | `Usage`_ |
`Installation`_ | `Project Structure`_ | `Design Principles`_ | `Scripts`_ |
`Contributing`_ | `Credits`_ | `More Info`_ | `License`_

Introduction
------------

**riko** is a Python `framework`_ for analyzing and processing streams of
structured data. It has synchronous and asynchronous APIs, supports parallel
execution, and is well suited for processing `rss`_ feeds.

With riko, you can

- Read csv/xml/json/html files
- Create text and data processing workflows via modular `pipes`_
- Parse, extract, and process rss feeds
- Create awesome `mashups`_, APIs, and maps
- Perform parallel processing via cpus/processors or threads
- and much more...

Requirements
------------

riko has been tested and is known to work on Python 2.7, 3.4, and 3.5;
PyPy 4.0; and PyPy3 2.4

Optional Dependencies
^^^^^^^^^^^^^^^^^^^^^

=======================  ============  =======================
Feature                  Dependency    Installation
=======================  ============  =======================
Async API                `Twisted`_    ``pip install twisted``
Accelerated xml parsing  `lxml`_ [#]_  ``pip install lxml``
=======================  ============  =======================

Notes
^^^^^

.. [#] If ``lxml`` isn't present, riko will default to the builtin Python xml parser

Word Count
----------

In this example, we use several `pipes`_ to count the words on a webpage.

.. code-block:: python

    >>> import itertools as it
    >>> from riko import get_url
    >>> from riko.modules.pipefetchpage import pipe as fetchpage
    >>> from riko.modules.pipestrreplace import pipe as strreplace
    >>> from riko.modules.pipestringtokenizer import pipe as stringtokenizer
    >>> from riko.modules.pipecount import pipe as count
    >>>
    >>> ### Set the pipe configurations ###
    >>> #
    >>> # Notes:
    >>> #   - `get_url` just looks up files in the `data` directory to simplify
    >>> #      testing
    >>> #   - the `detag` option will strip all html tags from the result
    >>> url = get_url('users.jyu.fi_~atsoukka_cgi_bin_aarresaari.html')
    >>> fetch_conf = {'url': url, 'start': '<body>', 'end': '</body>', 'detag': True}
    >>> replace_conf = {'rule': {'find': '\\n', 'replace': ' '}}
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
    >>> words = stringtokenizer(replaced, conf={'delimiter': ' '}, emit=True)
    >>> counts = count(words)
    >>> next(counts)
    {'count': 70}

    >>> ### Alternatively, create a SyncPipe workflow ###
    >>> #
    >>> # `SyncPipe` is a workflow convenience class that enables method
    >>> # chaining and parallel processing
    >>> from riko.lib.collections import SyncPipe
    >>>
    >>> counts = (SyncPipe('fetchpage', conf=fetch_conf)
    ...     .strreplace(conf=replace_conf, assign='content')
    ...     .stringtokenizer(conf={'delimiter': ' '}, emit=True)
    ...     .count()
    ...     .output)
    >>>
    >>> next(counts)
    {'count': 70}

Motivation
----------

Why I built riko
^^^^^^^^^^^^^^^^

Yahoo! Pipes [#]_ was a user and developer friendly web application that allowed
you to "aggregate, manipulate, and mashup content from around the web."

Desiring the flexibility to create custom pipes, I looked for an open source
alternative and found `pipe2py`_. It translated the json configuration from a
Yahoo pipe into python code. pipe2py suited my needs at the time but was
unmaintained and lacked asynchronous and parallel processing APIs.

I designed **riko** to address the shortcomings of pipe2py without the burden
of providing Yahoo! Pipes compatibility. To that extent, riko contains
~40 built-in modules, aka ``pipes``, that allow you to programatically
recreate much of what you previously could on Yahoo! Pipes.

Why you should use riko
^^^^^^^^^^^^^^^^^^^^^^^

``riko`` provides a number of benefits / differences from other stream processing
applications such as Huginn, Flink, Spark, and Storm [#]_. Namely:

- small footprint (CPU and memory usage)
- native RSS support
- simple installation and usage
- `pypy support`_
- modular ``pipes`` to filter, sort, and modify feeds

Unlike Spark et al., riko is not distributed, i.e., able to run on a cluster of
servers. The main benefit this brings is a simple installation process
(no dependencies outside of python) and low resource usage. Next, of
the other processors mentioned, only riko and Huginn natively support RSS feeds.

Compared to Huginn however, riko has a much narrower focus. riko lacks a gui,
doesn't continually monitor feeds for new data, and can't react to specific
events. Additionally, riko implements streams as iterators. Iterators have the
benefit of low memory usage, but are "pull" based and only support a single
consumer.

The following table summaries these observations:

===========  ===========  =========  ===  =======================  ========  ===========
Framework    Stream Type  Footprint  RSS  no outside dependencies  CEP [#]_  distributed
===========  ===========  =========  ===  =======================  ========  ===========
riko         pull         small      √    √
Huginn       push         med        √                             √
Others       push         large                                    √         √
===========  ===========  =========  ===  =======================  ========  ===========

For more detailed information, please check-out the `FAQ`_.

Notes
^^^^^

.. [#] Yahoo discontinued Yahoo! Pipes in ???, but you can view what `remains`_
.. [#] `Huginn`_, `Flink`_, `Spark`_, and `Storm`_
.. [#] `Complex Event Processing`_

Usage
-----

riko is intended to be used directly as a Python library.

Usage Index
^^^^^^^^^^^

- `Fetching feeds`_
- `Synchronous processing`_
- `Parallel processing`_
- `Asynchronous processing`_
- `Cookbook`_

Fetching feeds
^^^^^^^^^^^^^^

riko can read both local and remote filepaths via ``source`` pipes. All source
pipes return equivalent `feed` iterators, i.e., a generator of dictionaries,
aka items.

.. code-block:: python

    >>> from itertools import chain
    >>> from riko import get_url
    >>> from riko.modules.pipefetch import pipe as fetch
    >>> from riko.modules.pipefetchdata import pipe as fetchdata
    >>> from riko.modules.pipefetchsitefeed import pipe as fetchsitefeed
    >>> from riko.modules.pipefeedautodiscovery import pipe as autodiscovery
    >>>
    >>> ### Fetch a url ###
    >>> feed = fetchdata(conf={'url': 'http://site.com/file.xml'})
    >>>
    >>> ### Fetch a filepath ###
    >>> #
    >>> # Note: `get_url` just looks up files in the `data` directory
    >>> # to simplify testing
    >>> feed = fetchdata(conf={'url': get_url('quote.json')})
    >>>
    >>> ### View the fetched data ###
    >>> item = next(feed)
    >>> item['list']['resources'][0]['resource']['fields']['symbol']
    'KRW=X'

    >>> ### Fetch an rss feed ###
    >>> feed = fetch(conf={'url': get_url('feed.xml')})
    >>>
    >>> ### Fetch the first rss feed found ###
    >>> feed = fetchsitefeed(conf={'url': get_url('edition.cnn.html')})
    >>>
    >>> ### Find all rss links ###
    >>> url = get_url('www.bbc.co.uk_news.html')
    >>> entries = autodiscovery(conf={'url': url})
    >>> urls = (e['link'] for e in entries)
    >>>
    >>> ### Fetch multiple links ###
    >>> feed = chain.from_iterable(fetch(conf={'url': url}) for url in urls)
    >>>
    >>> ### Alternatively, create a SyncCollection ###
    >>> #
    >>> # `SyncCollection` is a url fetching convenience class with support for
    >>> # parallel processing
    >>> from riko.lib.collections import SyncCollection
    >>>
    >>> sources = [{'url': url} for url in urls]
    >>> feed = SyncCollection(sources).fetch()
    >>>
    >>> ### View the fetched rss feed(s) ###
    >>> #
    >>> # Note: regardless of how you fetch an rss feed, it will have the same
    >>> # structure
    >>> item = next(feed)
    >>> sorted(item.keys())
    [
        'author', 'author.name', 'author.uri', 'comments', 'content',
        'dc:creator', 'id', 'link', 'pubDate', 'summary', 'title',
        'updated', 'updated_parsed', 'y:id', 'y:published', 'y:title']
    >>> item['author']
    'Liam Green-Hughes'

Please see the `FAQ`_ for a complete list of supported `file types`_ and
`protocols`_


Synchronous processing
^^^^^^^^^^^^^^^^^^^^^^

riko can modify feeds by combining any of the 40 built-in ``pipes``

.. code-block:: python

    >>> from itertools import chain
    >>> from riko import get_url
    >>> from riko.modules.pipefetch import pipe as fetch
    >>> from riko.modules.pipefilter import pipe as pfilter
    >>> from riko.modules.pipesubelement import pipe as subelement
    >>> from riko.modules.piperegex import pipe as regex
    >>> from riko.modules.pipesort import pipe as sort
    >>>
    >>> ### Set the pipe configurations ###
    >>> #
    >>> # Notes:
    >>> #   - `get_url` just looks up files in the `data` directory to simplify
    >>> #     testing
    >>> #   - the `dotall` option is used to match `.*` across newlines
    >>> fetch_conf = {'url': get_url('feed.xml')}
    >>> filter_rule = {'field': 'y:published', 'op': 'before', 'value': '2/5/09'}
    >>> sub_conf = {'path': 'content.value'}
    >>> match = r'(.*href=")([\w:/.@]+)(".*)'
    >>> regex_rule = {'field': 'content', 'match': match, 'replace': '$2', 'dotall': True}
    >>> sort_conf = {'rule': {'sort_key': 'content', 'sort_dir': 'desc'}}
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
    >>> feed = fetch(conf=fetch_conf)
    >>> filtered = pfilter(feed, conf={'rule': filter_rule})
    >>> extracted = (subelement(i, conf=sub_conf, emit=True) for i in filtered)
    >>> flat_extract = chain.from_iterable(extracted)
    >>> matched = (regex(i, conf={'rule': regex_rule}) for i in flat_extract)
    >>> flat_match = chain.from_iterable(matched)
    >>> sorted_match = sort(flat_match, conf=sort_conf)
    >>> next(sorted_match)
    {'content': 'mailto:mail@writetoreply.org'}

    >>> ### Alternatively, create a SyncPipe workflow ###
    >>> #
    >>> # `SyncPipe` is a workflow convenience class that enables method
    >>> # chaining, parallel processing, and eliminates the manual `map` and
    >>> # `chain` steps
    >>> from riko.lib.collections import SyncPipe
    >>>
    >>> output = (SyncPipe('fetch', conf=fetch_conf)
    ...     .filter(conf={'rule': filter_rule})
    ...     .subelement(conf=sub_conf, emit=True)
    ...     .regex(conf={'rule': regex_rule})
    ...     .sort(conf=sort_conf)
    ...     .output)
    >>>
    >>> next(output)
    {'content': 'mailto:mail@writetoreply.org'}

Please see `Design Principles`_ for an explanation on why some pipes receive
an entire feed, e.g., ``pipefilter``, while others receive individual items, e.g.,
``pipesubelement``.

Please see `pipes`_ for a complete list of available pipes.

Parallel processing
^^^^^^^^^^^^^^^^^^^^^^^

An example using riko's ThreadPool based parallel API

.. code-block:: python

    >>> from riko import get_url
    >>> from riko.lib.collections import SyncPipe
    >>>
    >>> ### Set the pipe configurations ###
    >>> #
    >>> # Notes:
    >>> #   - `get_url` just looks up files in the `data` directory to simplify
    >>> #     testing
    >>> #   - the `dotall` option is used to match `.*` across newlines
    >>> url = get_url('feed.xml')
    >>> filter_rule1 = {'field': 'y:published', 'op': 'before', 'value': '2/5/09'}
    >>> match = r'(.*href=")([\w:/.@]+)(".*)'
    >>> regex_rule = {'field': 'content', 'match': match, 'replace': '$2', 'dotall': True}
    >>> filter_rule2 = {'field': 'content', 'op': 'contains', 'value': 'file'}
    >>> strtransform_conf = {'rule': {'transform': 'rstrip', 'args': '/'}}
    >>>
    >>> ### Create a parallel SyncPipe workflow ###
    >>> #
    >>> # The following workflow will:
    >>> #   1. fetch the rss feed
    >>> #   2. filter for items published before 2/5/2009
    >>> #   3. extract the path `content.value` from each feed item
    >>> #   4. replace the extracted text with the last href url contained
    >>> #      within it
    >>> #   5. filter for items with local file urls (which happen to be rss
    >>> #      feeds)
    >>> #   6. strip any trailing `\` from the url
    >>> #   7. remove duplicate urls
    >>> #   8. fetch each rss feed
    >>> #   9. Merge the rss feeds into a list
    >>> feed = (SyncPipe('fetch', conf={'url': url}, parallel=True)
    ...     .filter(conf={'rule': filter_rule1})
    ...     .subelement(conf=sub_conf, emit=True)
    ...     .regex(conf={'rule': regex_rule})
    ...     .filter(conf={'rule': filter_rule2})
    ...     .strtransform(conf=strtransform_conf)
    ...     .uniq(conf={'uniq_key': 'strtransform'})
    ...     .fetch(conf={'url': {'subkey': 'strtransform'}})
    ...     .list)
    >>>
    >>> len(feed)
    25

Asynchronous processing
^^^^^^^^^^^^^^^^^^^^^^^

An example using riko's Twisted powered asynchronous API

.. code-block:: python

    >>> from twisted.internet.task import react
    >>> from twisted.internet.defer import inlineCallbacks
    >>> from riko import get_url
    >>> from riko.twisted.collections import AsyncPipe
    >>>
    >>> ### Set the pipe configurations ###
    >>> #
    >>> # Notes:
    >>> #   - `get_url` just looks up files in the `data` directory to simplify
    >>> #     testing
    >>> #   - the `dotall` option is used to match `.*` across newlines
    >>> url = get_url('feed.xml')
    >>> filter_rule1 = {'field': 'y:published', 'op': 'before', 'value': '2/5/09'}
    >>> match = r'(.*href=")([\w:/.@]+)(".*)'
    >>> regex_rule = {'field': 'content', 'match': match, 'replace': '$2', 'dotall': True}
    >>> filter_rule2 = {'field': 'content', 'op': 'contains', 'value': 'file'}
    >>> strtransform_conf = {'rule': {'transform': 'rstrip', 'args': '/'}}
    >>>
    >>> ### Create a AsyncPipe workflow ###
    >>> #
    >>> # See `Parallel processing` above for the steps this performs
    >>> @inlineCallbacks
    ... def run(reactor):
    ...     feed = yield (AsyncPipe('fetch', conf={'url': url})
    ...         .filter(conf={'rule': filter_rule1})
    ...         .subelement(conf=sub_conf, emit=True)
    ...         .regex(conf={'rule': regex_rule})
    ...         .filter(conf={'rule': filter_rule2})
    ...         .strtransform(conf=strtransform_conf)
    ...         .uniq(conf={'uniq_key': 'strtransform'})
    ...         .fetch(conf={'url': {'subkey': 'strtransform'}})
    ...         .list)
    ...
    ...     print(len(feed))
    ...
    >>> react(run)
    25

Cookbook
^^^^^^^^

Please see the `cookbook`_ or ipython `notebook`_ for more examples.

Notes
^^^^^

.. [#] http://pandas.pydata.org/pandas-docs/stable/10min.html#min
.. [#] https://csvkit.readthedocs.org/en/0.9.1/cli.html#processing
.. [#] https://github.com/mapbox?utf8=%E2%9C%93&query=geojson

Installation
------------

(You are using a `virtualenv`_, right?)

At the command line, install riko using either ``pip`` (*recommended*)

.. code-block:: bash

    pip install riko

or ``easy_install``

.. code-block:: bash

    easy_install riko

Please see the `installation doc`_ for more details.

Project Structure
-----------------

.. code-block:: bash

    ┌── CONTRIBUTING.rst
    ├── LICENSE
    ├── MANIFEST.in
    ├── Makefile
    ├── README.rst
    ├── bin
    │   └── run
    ├── data/*
    ├── dev-requirements.txt
    ├── docs
    │   ├── AUTHORS.rst
    │   ├── CHANGES.rst
    │   ├── COOKBOOK.rst
    │   ├── FAQ.rst
    │   ├── INSTALLATION.rst
    │   └── TODO.rst
    ├── examples
    │   ├── __init__.py
    │   ├── pipe_1a0ea1b39a8f261d0339a12fb5f0f03e.py
    │   ├── pipe_4f26297843f4952fad920af5990ddc50.py
    │   ├── pipe_679e2c544332e978b15b6b163767975f.py
    │   ├── pipe_a3d1afa31f0a24cc51dcbe79f1590343.py
    │   ├── pipe_base.py
    │   ├── pipe_gigs.py
    │   ├── pipe_test.py
    │   ├── usage.ipynb
    │   └── usage.py
    ├── helpers/*
    ├── manage.py
    ├── py2-requirements.txt
    ├── requirements.txt
    ├── riko
    │   ├── __init__.py
    │   ├── lib
    │   │   ├── __init__.py
    │   │   ├── autorss.py
    │   │   ├── collections.py
    │   │   ├── dotdict.py
    │   │   ├── log.py
    │   │   └── utils.py
    │   ├── modules/*
    │   └── twisted
    │       ├── __init__.py
    │       ├── collections.py
    │       └── utils.py
    ├── setup.cfg
    ├── setup.py
    ├── tests
    │   ├── __init__.py
    │   └── standard.rc
    └── tox.ini

Design Principles
-----------------

The primary data structures in riko are the ``item``, and ``feed``. An ``item``
is a simple dictionary, and a ``feed`` is an iterator of ``items``. You can
create a feed manually with something as simple as
``[{'content': 'hello world'}]``. The primary way to manipulate a ``feed`` in
riko is via a ``pipe``. A ``pipe`` is simply a function that accepts either a
``feed`` or ``item``, and returns an iterator of ``item``s. You can create a
``workflow`` by using the output of one ``pipe`` as the input to another
``pipe``.

riko ``pipes`` come in two flavors; ``operator`` and ``processor``.
``operator``s operate on an entire feed at once and are unable to handle
individual items. Example ``operator``s include ``pipecount``, ``pipefilter``,
and ``pipereverse``.

.. code-block:: python

    >>> from riko.modules.pipereverse import pipe
    >>>
    >>> feed = [{'title': 'riko pt. 1'}, {'title': 'riko pt. 2'}]
    >>> next(pipe(feed))
    {'title': 'riko pt. 2'}

``processor``s process individual feed items and can be parallelized across
threads or processes. Example ``processor``s include ``pipefetchsitefeed``,
``pipehash``, ``pipeitembuilder``, and ``piperegex``.

.. code-block:: python

    >>> from riko.modules.pipehash import pipe
    >>>
    >>> item = {'title': 'riko pt. 1'}
    >>> feed = pipe(item, field='title')
    >>> next(feed)
    {'title': 'riko pt. 1', 'hash': 2853617420}

Some ``processor``s, e.g. ``pipestringtokenizer`` return multiple results.

.. code-block:: python

    >>> from riko.modules.pipestringtokenizer import pipe
    >>>
    >>> item = {'title': 'riko pt. 1'}
    >>> tokenizer_conf = {'delimiter': ' '}
    >>> feed = pipe(item, conf=tokenizer_conf, field='title')
    >>> next(feed)
    {
        'title': 'riko pt. 1',
        'stringtokenizer': [
            {'content': 'riko'},
            {'content': 'pt.'},
            {'content': '1'}]}

    >>> # In this case, if we just want the result, we can `emit` it instead
    >>> feed = pipe(item, conf=tokenizer_conf, field='title', emit=True)
    >>> next(feed)
    {'content': 'riko'}

``operator``s are split into sub-types of ``aggregator``
and ``composer``; and ``processor``s are split into sub-types of
``source`` and ``transformer``. ``aggregator``s, e.g., ``pipecount``, aggregate
all items of a feed into a single value while ``composer``s, e.g., ``pipefilter``
composed a new feed from a subset or all of the available items.

.. code-block:: python

    >>> from riko.modules.pipecount import pipe
    >>>
    >>> feed = [{'title': 'riko pt. 1'}, {'title': 'riko pt. 2'}]
    >>> next(pipe(feed))
    {'count': 2}

``source``s, e.g., ``pipefetchsitefeed``, can create a feed while
``transformer``s, e.g. ``pipehash`` can only transform items in a feed.

.. code-block:: python

    >>> from riko.modules.pipeitembuilder import pipe
    >>>
    >>> attrs = {'key': 'title', 'value': 'riko pt. 1'}
    >>> next(pipe(conf={'attrs': attrs}))
    {'title': 'riko pt. 1'}

The following table summaries these observations:

+-----------+-------------+-------+-------------+----------------+--------------+
| type      | sub-type    | input | output [#]_ | parallelizable | feed creator |
+-----------+-------------+-------+-------------+----------------+--------------+
| operator  | aggregator  | feed  | aggregation | false          | false        |
|           +-------------+-------+-------------+----------------+--------------+
|           | composer    | feed  | feed        | false          | false        |
+-----------+-------------+-------+-------------+----------------+--------------+
| processor | source      | item  | feed        | true           | true         |
|           +-------------+-------+-------------+----------------+--------------+
|           | transformer | item  | feed        | true           | false        |
+-----------+-------------+-------+-------------+----------------+--------------+

If you are unsure of the type of pipe you have, check its metadata.

.. code-block:: python

    >>> from riko.modules.pipefetchpage import asyncPipe
    >>> from riko.modules.pipecount import pipe
    >>>
    >>> asyncPipe.__dict__
    {'type': 'processor', 'sub_type': 'source'}
    >>> pipe.__dict__
    {'type': 'operator', 'name': 'count', 'sub_type': 'aggregator'}

The ``SyncPipe`` and ``AsyncPipe`` classes (among other things) perform this
check for you to allow for convenient method chaining and transparent
parallelization.

.. code-block:: python

    >>> from riko.lib.collections import SyncPipe
    >>>
    >>> attrs = [
    ...     {'key': 'title', 'value': 'riko pt. 1'},
    ...     {'key': 'content', 'value': "Let's talk about riko!"}]
    >>> sync_pipe = SyncPipe('itembuilder', conf={'attrs': attrs})
    >>> sync_pipe.hash().list[0]
    [
        {
            'title': 'riko pt. 1',
            'content': "Let's talk about riko!",
            'hash': 1346301218}]

Please see the `cookbook`_ for advanced examples including how to wire in
vales from other pipes or accept user input.

Notes
^^^^^

.. [#] the data structures of an ``aggregation`` and ``feed`` are the same: an iterator of dicts

Scripts
-------

riko comes with a built in task manager ``manage.py``

Setup
^^^^^

.. code-block:: bash

    pip install -r dev-requirements.txt

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

Shoutout to `pipe2py`_ for heavily inspiring riko. riko started out as a fork
of pipe2py, but has since diverged so much that little (if any) of the original
code-base remains.

More Info
---------

- `FAQ`_
- `cookbook`_
- ipython `notebook`_

License
-------

riko is distributed under the `MIT License`_.

.. |travis| image:: https://img.shields.io/travis/reubano/riko/master.svg
    :target: https://travis-ci.org/reubano/riko

.. |versions| image:: https://img.shields.io/pypi/pyversions/riko.svg
    :target: https://pypi.python.org/pypi/riko

.. |pypi| image:: https://img.shields.io/pypi/v/riko.svg
    :target: https://pypi.python.org/pypi/riko

.. _rss: https://wikipedia.org/?
.. _mashups: https://wikipedia.org/?
.. _pipe2py: https://github.com/?/pipe2py
.. _Huginn: https://github.com/?/huginn
.. _Flink: ?
.. _Spark: ?
.. _Storm: ?
.. _Complex Event Processing: ?
`remains`_ http://???
.. _framework: #usage
.. _lxml: http://www.crummy.com/software/BeautifulSoup/bs4/doc/#installing-a-parser
.. _MIT License: http://opensource.org/licenses/MIT
.. _virtualenv: http://www.virtualenv.org/en/latest/index.html
.. _contributing doc: https://github.com/reubano/riko/blob/master/CONTRIBUTING.rst
.. _FAQ: https://github.com/reubano/riko/blob/master/docs/FAQ.rst
.. _pypy support: https://github.com/reubano/riko/blob/master/docs/FAQ.rst#pypy
.. _notebook: http://nbviewer.jupyter.org/github/reubano/riko/blob/master/examples/usage.ipynb
.. _pipes: https://github.com/reubano/riko/blob/master/docs/FAQ.rst#what-pipes-are-available
.. _file types: https://github.com/reubano/riko/blob/master/docs/FAQ.rst#what-file-types-are-supported
.. _protocols: https://github.com/reubano/riko/blob/master/docs/FAQ.rst#what-protocols-are-supported
.. _installation doc: https://github.com/reubano/riko/blob/master/docs/INSTALLATION.rst
.. _cookbook: https://github.com/reubano/riko/blob/master/docs/COOKBOOK.rst
