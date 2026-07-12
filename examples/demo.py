# vim: sw=4:ts=4:expandtab

r"""
riko demo
~~~~~~~~~

Word Count

    >>> from riko import get_path
    >>> from riko.collections import SyncPipe
    >>>
    >>> url = get_path('users.jyu.fi.html')
    >>> fetch_conf = {
    ...     'url': url, 'start': '<body>', 'end': '</body>', 'detag': True}
    >>> replace_conf = {'rule': {'find': '\\n', 'replace': ' '}}
    >>>
    >>> counts = (SyncPipe('fetchpage', conf=fetch_conf)
    ...     .strreplace(conf=replace_conf, assign='content')
    ...     .tokenizer(conf={'delimiter': ' '}, emit=True)
    ...     .count())
    >>>
    >>> next(counts)
    {'count': 70}

Fetching feeds

    >>> from riko.modules.fetch import pipe as fetch
    >>>
    >>> url = get_path('gawker.xml')
    >>> intersection = [
    ...     'author', 'author.name', 'author.uri', 'dc:creator', 'id', 'link',
    ...     'pubDate', 'summary', 'title', 'y:id', 'y:published', 'y:title']
    >>> feed = fetch(conf={'url': url})
    >>> item = next(feed)
    >>> set(item).issuperset(intersection)
    True
    >>> item['title'][:24]
    'This Is What A Celebrity'
    >>> item['link'][:23]
    'http://feeds.gawker.com'
"""

from typing import cast

from riko import get_path
from riko.collections import AsyncPipe, SyncPipe
from riko.types.modules import FetchPageConf

replace_conf = {"rule": {"find": "\n", "replace": " "}}
health = get_path("health.xml")
caltrain = get_path("caltrain.html")
start = '<body id="thebody" class="Level2">'
fetch_conf = FetchPageConf(
    {"url": caltrain, "start": start, "end": "</body>", "detag": True}
)


def pipe(test=False):
    s1 = SyncPipe("fetch", test=test, conf={"url": health})
    s2 = (
        SyncPipe("fetchpage", test=test, conf=fetch_conf)
        .strreplace(conf=replace_conf, assign="content")
        .tokenizer(conf={"delimiter": " "}, emit=True)
        .count()
    )

    return (s1, s2)


async def async_pipe(reactor, test=False):
    s1 = await AsyncPipe("fetch", test=test, conf={"url": health})
    s2 = await (
        AsyncPipe("fetchpage", test=test, conf=fetch_conf)
        .strreplace(conf=replace_conf, assign="content")
        .tokenizer(conf={"delimiter": " "}, emit=True)
        .count()
    )

    return (s1, s2)


if __name__ == "__main__":
    s1, s2 = pipe()

    if s1:
        print(cast(dict, next(s1))["title"])

    if s2:
        print(cast(dict, next(s2))["count"])
