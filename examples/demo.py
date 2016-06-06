# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab

"""
riko demo
~~~~~~~~~

Word Count

	>>> from riko.lib.collections import SyncPipe
	>>> from riko import get_path
	>>>
	>>> url = get_path('users.jyu.fi.html')
	>>> fetch_conf = {
	...     'url': url, 'start': '<body>', 'end': '</body>', 'detag': True}
	>>> replace_conf = {'rule': {'find': '\\n', 'replace': ' '}}
	>>>
	>>> counts = (SyncPipe('fetchpage', conf=fetch_conf)
	...     .strreplace(conf=replace_conf, assign='content')
	...     .stringtokenizer(conf={'delimiter': ' '}, emit=True)
	...     .count()
	...     .output)
	>>>
	>>> next(counts)
	{u'count': 70}

Fetching feeds

	>>> from riko.modules.pipefetch import pipe as fetch
	>>>
	>>> feed = fetch(conf={'url': 'https://news.ycombinator.com/rss'})
	>>> item = next(feed)
	>>> sorted(item.keys())
	[u'author.name', u'author.uri', 'comments', 'content', u'dc:creator', \
'link', u'pubDate', 'summary', 'title', 'updated', 'updated_parsed', u'y:id', \
u'y:published', u'y:title']
	>>> item['title'], item['link']  # doctest: +ELLIPSIS
	(u'...', u'http...')
"""
