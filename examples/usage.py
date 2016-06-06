# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab

"""
README examples
~~~~~~~~~~~~~~~

Word Count

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
    >>> fetch_conf = {
    ...     'url': url, 'start': '<body>', 'end': '</body>', 'detag': True}
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
    >>> next(counts) == {'count': 70}
    True

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
    >>> next(counts) == {'count': 70}
    True


Fetching feeds

    >>> from itertools import chain
    >>> from riko import get_path
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
    >>> # Note: `get_path` just looks up files in the `data` directory
    >>> # to simplify testing
    >>> feed = fetchdata(conf={'url': get_path('quote.json')})
    >>>
    >>> ### View the fetched data ###
    >>> item = next(feed)
    >>> item['list']['resources'][0]['resource']['fields']['symbol']
    u'KRW=X'

    >>> ### Fetch an rss feed ###
    >>> feed = fetch(conf={'url': get_path('feed.xml')})
    >>>
    >>> ### Fetch the first rss feed found ###
    >>> feed = fetchsitefeed(conf={'url': get_path('edition.cnn.html')})
    >>>
    >>> ### Find all rss links and fetch the feeds ###
    >>> url = get_path('www.bbc.co.uk_news.html')
    >>> entries = autodiscovery(conf={'url': url})
    >>> urls = (e['link'] for e in entries)
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
    >>> sorted(item.keys()) == [
    ...     'author', 'author.name', 'author.uri', 'comments', 'content',
    ...     'dc:creator', 'id', 'link', 'pubDate', 'summary', 'title',
    ...     'updated', 'updated_parsed', 'y:id', 'y:published', 'y:title']
    True
    >>> item['title'], item['author'], item['link']
    (u'Using NFC tags in the car', u'Liam Green-Hughes', \
u'http://www.greenhughes.com/content/using-nfc-tags-car')


Synchronous processing

    >>> from itertools import chain
    >>> from riko import get_path
    >>> from riko.modules.pipefetch import pipe as fetch
    >>> from riko.modules.pipefilter import pipe as pfilter
    >>> from riko.modules.pipesubelement import pipe as subelement
    >>> from riko.modules.piperegex import pipe as regex
    >>> from riko.modules.pipesort import pipe as sort
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
    >>> next(sorted_match) == {'content': 'mailto:mail@writetoreply.org'}
    True

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
    >>> next(output) == {'content': 'mailto:mail@writetoreply.org'}
    True


Parallel processing

    >>> from riko import get_path
    >>> from riko.lib.collections import SyncPipe
    >>>
    >>> ### Set the pipe configurations ###
    >>> #
    >>> # Notes `get_path` just looks up files in the `data` directory to
    >>> # simplify testing
    >>> url = get_path('feed.xml')
    >>> filter_rule1 = {
    ...     'field': 'y:published', 'op': 'before', 'value': '2/5/09'}
    >>> match = r'(.*href=")([\w:/.@]+)(".*)'
    >>> regex_rule = {'field': 'content', 'match': match, 'replace': '$2'}
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

    >>> from twisted.internet.task import react
    >>> from twisted.internet.defer import inlineCallbacks
    >>> from riko import get_path
    >>> from riko.twisted import utils as tu
    >>> from riko.twisted.collections import AsyncPipe
    >>>
    >>> ### Set the pipe configurations ###
    >>> #
    >>> # Notes:
    >>> #   - `get_path` just looks up files in the `data` directory to simplify
    >>> #     testing
    >>> #   - the `dotall` option is used to match `.*` across newlines
    >>> url = get_path('feed.xml')
    >>> filter_rule1 = {
    ...     'field': 'y:published', 'op': 'before', 'value': '2/5/09'}
    >>> match = r'(.*href=")([\w:/.@]+)(".*)'
    >>> regex_rule = {
    ...     'field': 'content', 'match': match, 'replace': '$2',
    ...     'dotall': True}
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
    >>> try:
    ...     react(run, _reactor=tu.FakeReactor())
    ... except SystemExit:
    ...     pass
    25


Design Principles

    # an operator
    >>> from riko.modules.pipereverse import pipe
    >>>
    >>> feed = [{'title': 'riko pt. 1'}, {'title': 'riko pt. 2'}]
    >>> next(pipe(feed))
    {u'title': u'riko pt. 2'}

    # a processor
    >>> from riko.modules.pipehash import pipe
    >>>
    >>> item = {'title': 'riko pt. 1'}
    >>> feed = pipe(item, field='title')
    >>> next(feed) == {
    ...     'title': 'riko pt. 1', 'hash': 3946887032}
    True
    >>> from riko.modules.pipestringtokenizer import pipe
    >>>
    >>> item = {'title': 'riko pt. 1'}
    >>> tokenizer_conf = {'delimiter': ' '}
    >>> feed = pipe(item, conf=tokenizer_conf, field='title')
    >>> next(feed) == {
    ...     'title': 'riko pt. 1',
    ...     'stringtokenizer': [
    ...         {'content': 'riko'},
    ...         {'content': 'pt.'},
    ...         {'content': '1'}]}
    True
    >>> # In this case, if we just want the result, we can `emit` it instead
    >>> feed = pipe(item, conf=tokenizer_conf, field='title', emit=True)
    >>> next(feed)
    {u'content': 'riko'}

    # an aggregator
    >>> from riko.modules.pipecount import pipe
    >>>
    >>> feed = [{'title': 'riko pt. 1'}, {'title': 'riko pt. 2'}]
    >>> next(pipe(feed))
    {u'count': 2}

    # a source
    >>> from riko.modules.pipeitembuilder import pipe
    >>>
    >>> attrs = {'key': 'title', 'value': 'riko pt. 1'}
    >>> next(pipe(conf={'attrs': attrs}))
    {u'title': u'riko pt. 1'}

    # check metadata
    >>> from riko.modules.pipefetchpage import asyncPipe
    >>> from riko.modules.pipecount import pipe
    >>>
    >>> asyncPipe.__dict__ == {'type': 'processor', 'sub_type': 'source'}
    True
    >>> pipe.__dict__ == {
    ...     'type': 'operator', 'name': 'count', 'sub_type': 'aggregator'}
    True

    # SyncPipe usage
    >>> from riko.lib.collections import SyncPipe
    >>>
    >>> attrs = [
    ...     {'key': 'title', 'value': 'riko pt. 1'},
    ...     {'key': 'content', 'value': "Let's talk about riko!"}]
    >>> sync_pipe = SyncPipe('itembuilder', conf={'attrs': attrs})
    >>> sync_pipe.hash().list[0] == {
    ...     'title': 'riko pt. 1',
    ...     'content': "Let's talk about riko!",
    ...     'hash': 1589640534}
    True

    # Alternate conf usage
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
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *
