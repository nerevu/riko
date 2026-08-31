# vim: sw=4:ts=4:expandtab

"""
Fetches a feed and counts the words on the fetched page.

The equivalent word-count and feed-fetching doctests live in ``README.rst``.

Examples:
    Run it::

        run-pipe demo

"""

from typing import cast

from riko.collections import AsyncPipe, SyncPipe
from riko.paths import get_path
from riko.types.modules import FetchPageConf, StrReplaceConf, StrReplaceConfRule

replace_conf = StrReplaceConf({"rule": StrReplaceConfRule(find="\n", replace=" ")})
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


async def async_pipe(test=False):
    s1 = await AsyncPipe("fetch", test=test, conf={"url": health})
    s2 = await (
        AsyncPipe("fetchpage", test=test, conf=fetch_conf)
        .strreplace(conf=replace_conf, assign="content")
        .tokenizer(conf={"delimiter": " "}, emit=True)
        .count()
    )

    return (s1, s2)


def print_results(result) -> None:
    feed, count = result
    print(cast(dict, next(feed))["title"])
    print(cast(dict, next(count))["count"])


def main(*, test: bool = False) -> None:
    print_results(pipe(test=test))


if __name__ == "__main__":
    main()
