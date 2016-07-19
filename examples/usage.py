# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab

"""
README examples
~~~~~~~~~~~~~~~

Word Count

    >>> import itertools as it
    >>> from riko import get_path
    >>> from riko.modules import fetchpage, strreplace, stringtokenizer, count
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
    >>> replace_kwargs = {'conf': replace_conf, 'assign': 'content'}
    >>> token_kwargs = {'conf': {'delimiter': ' '}, 'emit': True}
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
    >>> page = next(fetchpage.pipe(conf=fetch_conf))
    >>> replaced = next(strreplace.pipe(page, **replace_kwargs))
    >>> words = stringtokenizer.pipe(replaced, **token_kwargs)
    >>> counts = count.pipe(words, conf={'count_key': 'content'})
    >>> next(counts) == {'$': 2}
    True
    >>> next(counts) == {'$Date:': 1}
    True
    >>> next(counts) == {'$Revision:': 1}
    True

    >>> ### Alternatively, create a SyncPipe workflow ###
    >>> #
    >>> # `SyncPipe` is a workflow convenience class that enables method
    >>> # chaining and parallel processing
    >>> from riko.collections.sync import SyncPipe
    >>>
    >>> stream = (SyncPipe('fetchpage', conf=fetch_conf)
    ...     .strreplace(conf=replace_conf, assign='content')
    ...     .stringtokenizer(conf={'delimiter': ' '}, emit=True)
    ...     .count(conf={'count_key': 'content'})
    ...     .output)
    >>>
    >>> next(stream) == {'$': 2}
    True


Fetching feeds

    >>> from itertools import chain
    >>> from riko import get_path
    >>> from riko.modules import (
    ...     fetch, fetchdata, fetchsitefeed, feedautodiscovery)
    >>>
    >>> ### Fetch a url ###
    >>> stream = fetchdata.pipe(conf={'url': 'http://site.com/file.xml'})
    >>>
    >>> ### Fetch a filepath ###
    >>> #
    >>> # Note: `get_path` just looks up files in the `data` directory
    >>> # to simplify testing
    >>> stream = fetchdata.pipe(conf={'url': get_path('quote.json')})
    >>>
    >>> ### View the fetched data ###
    >>> item = next(stream)
    >>> item['list']['resources'][0]['resource']['fields']['symbol'] == 'KRW=X'
    True

    >>> ### Fetch an rss feed ###
    >>> stream = fetch.pipe(conf={'url': get_path('feed.xml')})
    >>>
    >>> ### Fetch the first rss feed found ###
    >>> stream = fetchsitefeed.pipe(conf={'url': get_path('cnn.html')})
    >>>
    >>> ### Find all rss links and fetch the feeds ###
    >>> url = get_path('bbc.html')
    >>> entries = feedautodiscovery.pipe(conf={'url': url})
    >>> urls = (e['link'] for e in entries)
    >>> stream = chain.from_iterable(fetch(conf={'url': url}) for url in urls)
    >>>
    >>> ### Alternatively, create a SyncCollection ###
    >>> #
    >>> # `SyncCollection` is a url fetching convenience class with support for
    >>> # parallel processing
    >>> from riko.collections.sync import SyncCollection
    >>>
    >>> sources = [{'url': url} for url in urls]
    >>> stream = SyncCollection(sources).fetch()
    >>>
    >>> ### View the fetched rss feed(s) ###
    >>> #
    >>> # Note: regardless of how you fetch an rss feed, it will have the same
    >>> # structure
    >>> intersection = [
    ...     'author', 'author.name', 'author.uri', 'dc:creator', 'id', 'link',
    ...     'pubDate', 'summary', 'title', 'y:id', 'y:published', 'y:title']
    >>> item = next(stream)
    >>> set(item).issuperset(intersection)
    True
    >>> item['title'] == 'Using NFC tags in the car'
    True
    >>> item['author'] == 'Liam Green-Hughes'
    True
    >>> item['link'] == 'http://www.greenhughes.com/content/using-nfc-tags-car'
    True


Synchronous processing

    >>> from itertools import chain
    >>> from riko import get_path
    >>> from riko.modules import fetch, filter, subelement, regex, sort
    >>>
    >>> ### Set the pipe configurations ###
    >>> #
    >>> # Note: `get_path` just looks up files in the `data` directory to
    >>> # simplify testing
    >>> fetch_conf = {'url': get_path('feed.xml')}
    >>> filter_rule = {
    ...     'field': 'y:published', 'op': 'before', 'value': '2/5/09'}
    >>> sub_conf = {'path': 'content.value'}
    >>> sub_kwargs = {'conf': sub_conf, 'emit': True}
    >>> match = r'(.*href=")([\w:/.@]+)(".*)'
    >>> regex_rule = {'field': 'content', 'match': match, 'replace': '$2'}
    >>> regex_conf = {'rule': regex_rule}
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
    >>> stream = fetch.pipe(conf=fetch_conf)
    >>> filtered = filter.pipe(stream, conf={'rule': filter_rule})
    >>> extracted = (subelement.pipe(i, **sub_kwargs) for i in filtered)
    >>> flat_extract = chain.from_iterable(extracted)
    >>> matched = (regex.pipe(i, conf=regex_conf) for i in flat_extract)
    >>> flat_match = chain.from_iterable(matched)
    >>> sorted_match = sort.pipe(flat_match, conf=sort_conf)
    >>> next(sorted_match) == {'content': 'mailto:mail@writetoreply.org'}
    True

    >>> ### Alternatively, create a SyncPipe workflow ###
    >>> #
    >>> # `SyncPipe` is a workflow convenience class that enables method
    >>> # chaining, parallel processing, and eliminates the manual `map` and
    >>> # `chain` steps
    >>> from riko.collections.sync import SyncPipe
    >>>
    >>> stream = (SyncPipe('fetch', conf=fetch_conf)
    ...     .filter(conf={'rule': filter_rule})
    ...     .subelement(conf=sub_conf, emit=True)
    ...     .regex(conf={'rule': regex_rule})
    ...     .sort(conf=sort_conf)
    ...     .output)
    >>>
    >>> next(stream) == {'content': 'mailto:mail@writetoreply.org'}
    True


Parallel processing

    >>> from riko import get_path
    >>> from riko.collections.sync import SyncPipe
    >>>
    >>> ### Set the pipe configurations ###
    >>> #
    >>> # Notes `get_path` just looks up files in the `data` directory to
    >>> # simplify testing
    >>> url = get_path('feed.xml')
    >>> sub_conf = {'path': 'content.value'}
    >>> match = r'(.*href=")([\w:/.@]+)(".*)'
    >>> regex_rule = {'field': 'content', 'match': match, 'replace': '$2'}
    >>> filter_rule = {'field': 'content', 'op': 'contains', 'value': 'file'}
    >>> strtransform_conf = {'rule': {'transform': 'rstrip', 'args': '/'}}
    >>>
    >>> ### Create a parallel SyncPipe workflow ###
    >>> #
    >>> # The following workflow will:
    >>> #   1. fetch the rss feed
    >>> #   3. extract the path `content.value` from each feed item
    >>> #   4. replace the extracted text with the last href url contained
    >>> #      within it
    >>> #   5. filter for items with local file urls (which happen to be rss
    >>> #      feeds)
    >>> #   6. strip any trailing `\` from the url
    >>> #   7. remove duplicate urls
    >>> #   8. fetch each rss feed
    >>> #   9. Merge the rss feeds into a list
    >>> stream = (SyncPipe('fetch', conf={'url': url}, parallel=True)
    ...     .subelement(conf=sub_conf, emit=True)
    ...     .regex(conf={'rule': regex_rule})
    ...     .filter(conf={'rule': filter_rule})
    ...     .strtransform(conf=strtransform_conf)
    ...     .uniq(conf={'uniq_key': 'strtransform'})
    ...     .fetch(conf={'url': {'subkey': 'strtransform'}})
    ...     .list)
    >>>
    >>> len(stream)
    25


Asynchronous processing

    >>> from riko import get_path
    >>> from riko.bado import coroutine, react, _issync, _isasync
    >>> from riko.bado.mock import FakeReactor
    >>> from riko.collections.async import AsyncPipe
    >>>
    >>> ### Set the pipe configurations ###
    >>> #
    >>> # Notes:
    >>> #   - `get_path` just looks up files in the `data` directory to simplify
    >>> #     testing
    >>> #   - the `dotall` option is used to match `.*` across newlines
    >>> url = get_path('feed.xml')
    >>> sub_conf = {'path': 'content.value'}
    >>> match = r'(.*href=")([\w:/.@]+)(".*)'
    >>> regex_rule = {
    ...     'field': 'content', 'match': match, 'replace': '$2',
    ...     'dotall': True}
    >>> filter_rule = {'field': 'content', 'op': 'contains', 'value': 'file'}
    >>> strtransform_conf = {'rule': {'transform': 'rstrip', 'args': '/'}}
    >>>
    >>> ### Create an AsyncPipe workflow ###
    >>> #
    >>> # See `Parallel processing` above for the steps this performs
    >>> @coroutine
    ... def run(reactor):
    ...     stream = yield (AsyncPipe('fetch', conf={'url': url})
    ...         .subelement(conf=sub_conf, emit=True)
    ...         .regex(conf={'rule': regex_rule})
    ...         .filter(conf={'rule': filter_rule})
    ...         .strtransform(conf=strtransform_conf)
    ...         .uniq(conf={'uniq_key': 'strtransform'})
    ...         .fetch(conf={'url': {'subkey': 'strtransform'}})
    ...         .list)
    ...
    ...     print(len(stream))
    ...
    >>> if _issync:
    ...     25
    ... else:
    ...     try:
    ...         react(run, _reactor=FakeReactor())
    ...     except SystemExit:
    ...         pass
    25


Design Principles

    # an operator
    >>> from riko.modules.reverse import pipe
    >>>
    >>> stream = [{'title': 'riko pt. 1'}, {'title': 'riko pt. 2'}]
    >>> next(pipe(stream)) == {'title': 'riko pt. 2'}
    True

    # a transformer
    >>> import ctypes
    >>> from riko.modules.hash import pipe
    >>>
    >>> _hash = ctypes.c_uint(hash('riko pt. 1')).value
    >>> item = {'title': 'riko pt. 1'}
    >>> stream = pipe(item, field='title')
    >>> next(stream) == {'title': 'riko pt. 1', 'hash': _hash}
    True
    >>> from riko.modules.stringtokenizer import pipe
    >>>
    >>> item = {'title': 'riko pt. 1'}
    >>> tokenizer_conf = {'delimiter': ' '}
    >>> stream = pipe(item, conf=tokenizer_conf, field='title')
    >>> next(stream) == {
    ...     'title': 'riko pt. 1',
    ...     'stringtokenizer': [
    ...         {'content': 'riko'},
    ...         {'content': 'pt.'},
    ...         {'content': '1'}]}
    True
    >>> # In this case, if we just want the result, we can `emit` it instead
    >>> stream = pipe(item, conf=tokenizer_conf, field='title', emit=True)
    >>> next(stream) == {'content': 'riko'}
    True

    # an aggregator
    >>> from riko.modules.count import pipe
    >>>
    >>> stream = [{'title': 'riko pt. 1'}, {'title': 'riko pt. 2'}]
    >>> next(pipe(stream)) == {'count': 2}
    True

    # a source
    >>> from riko.modules.itembuilder import pipe
    >>>
    >>> attrs = {'key': 'title', 'value': 'riko pt. 1'}
    >>> next(pipe(conf={'attrs': attrs})) == {'title': 'riko pt. 1'}
    True


    # check metadata
    >>> from riko.modules import fetchpage, count
    >>>
    >>> if _isasync:
    ...     async_resp = ('processor', 'fetchpage', 'source')
    ... else:
    ...     async_resp = (None, None, None)
    >>>
    >>> async_pdict = fetchpage.async_pipe.__dict__
    >>> (async_pdict.get('type'), async_pdict.get('name')) == async_resp[:2]
    True
    >>> async_pdict.get('sub_type') == async_resp[2]
    True
    >>> pdict = count.pipe.__dict__
    >>> sync_resp = ('operator', 'count', 'aggregator')
    >>> (pdict['type'], pdict['name'], pdict['sub_type']) == sync_resp
    True

    # SyncPipe usage
    >>> from riko.collections.sync import SyncPipe
    >>>
    >>> _hash = ctypes.c_uint(hash("Let's talk about riko!")).value
    >>> attrs = [
    ...     {'key': 'title', 'value': 'riko pt. 1'},
    ...     {'key': 'content', 'value': "Let's talk about riko!"}]
    >>> sync_pipe = SyncPipe('itembuilder', conf={'attrs': attrs})
    >>> sync_pipe.hash().list[0] == {
    ...     'title': 'riko pt. 1',
    ...     'content': "Let's talk about riko!",
    ...     'hash': _hash}
    True

    # Alternate conf usage
    >>> from riko import get_path
    >>> from riko.modules.fetch import pipe
    >>>
    >>> intersection = [
    ...     'author', 'author.name', 'author.uri', 'dc:creator', 'id', 'link',
    ...     'pubDate', 'summary', 'title', 'y:id', 'y:published', 'y:title']
    >>> conf = {'url': {'subkey': 'url'}}
    >>> result = pipe({'url': get_path('feed.xml')}, conf=conf)
    >>> set(next(result)).issuperset(intersection)
    True
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *

from pprint import pprint
from riko.collections.sync import SyncPipe

attrs = [
    {'key': 'title', 'value': 'riko pt. 1'},
    {'key': 'content', 'value': "Let's talk about riko!"}]

ib_conf = {'attrs': attrs}


def pipe(test=False):
    flow = SyncPipe('itembuilder', conf=ib_conf, test=test).hash()

    for i in flow.output:
        pprint(i)
