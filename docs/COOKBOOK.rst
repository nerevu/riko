riko Cookbook
=============

Index
-----

`User input`_ | `Alternate conf value entry`_ | `Alternate workflow creation`_

User input
----------

Some workflows require user input (via the ``pipeinput`` pipe). By default,
``pipeinput`` prompts the user via the console, but in some situations this may
not be appropriate, e.g., testing or integrating with a website. In such cases,
the input values can instead be read from the workflow's ``inputs`` kwarg (a
set of values passed into every pipe).

.. code-block:: python

    >>> from riko.modules.pipeinput import pipe
    >>> conf = {'prompt': 'How old are you?', 'type': 'int'}
    >>> pipe(conf=conf, inputs={'content': '30'}).next()
    {'content': 30}

Alternate ``conf`` value entry
------------------------------

Some workflows have ``conf`` values that are wired from other pipes

.. code-block:: python

    >>> from riko import get_path
    >>> from riko.modules.pipefetch import pipe
    >>>
    >>> conf = {'url': {'subkey': 'url'}}
    >>> result = pipe({'url': get_path('feed.xml')}, conf=conf)
    >>> set(next(result).keys()) == {
    ...     'updated', 'updated_parsed', 'pubDate', 'author', 'y:published',
    ...     'title', 'comments', 'summary', 'content', 'link', 'y:title',
    ...     'dc:creator', 'author.uri', 'author.name', 'id', 'y:id'}
    True

Alternate workflow creation
------------------------------

In addition to `class based workflows`_ ``riko`` supports a pure functional style

.. code-block:: python

    >>> import itertools as it
    >>> from riko import get_path
    >>> from riko.modules.pipefetchpage import pipe as fetchpage
    >>> from riko.modules.pipestrreplace import pipe as strreplace
    >>> from riko.modules.pipestringtokenizer import pipe as stringtokenizer
    >>> from riko.modules.pipecount import pipe as count
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
    >>> words = stringtokenizer(replaced, conf={'delimiter': ' '}, emit=True)
    >>> counts = count(words)
    >>> next(counts)
    {'count': 70}

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

.. _class based workflows: https://github.com/reubano/riko/blob/master/README.rst#synchronous-processing
