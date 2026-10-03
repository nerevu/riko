# vim: sw=4:ts=4:expandtab

"""
Fetches a feed and counts the words on the fetched page.

The equivalent word-count and feed-fetching doctests live in ``README.rst``.

Examples:

    Run it::

        run-pipe demo

"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from riko import Pipeline, get_path
from riko.types.modules import FetchPageConf, StrReplaceConf, StrReplaceConfRule

if TYPE_CHECKING:
    from riko.types import AsyncStream, Item, Items

replace_conf = StrReplaceConf({"rule": StrReplaceConfRule(find="\n", replace=" ")})
health = get_path("health.xml")
caltrain = get_path("caltrain.html")
start = '<body id="thebody" class="Level2">'
fetch_conf = FetchPageConf(
    {"url": caltrain, "start": start, "end": "</body>", "detag": True}
)


def pipe(test: bool = False) -> list[Item]:
    s1 = Pipeline.from_module("fetch", conf={"url": health})
    s2 = (
        Pipeline.from_module("fetchpage", conf=fetch_conf)
        .strreplace(conf=replace_conf, options={"assign": "content"})
        .tokenizer(conf={"delimiter": " "}, options={"emit": True})
        .count()
    )

    return [next(iter(s1)), next(iter(s2))]


async def async_pipe(test: bool = False) -> AsyncStream:
    s1 = Pipeline.from_module("fetch", conf={"url": health})
    s2 = (
        Pipeline.from_module("fetchpage", conf=fetch_conf)
        .strreplace(conf=replace_conf, options={"assign": "content"})
        .tokenizer(conf={"delimiter": " "}, options={"emit": True})
        .count()
    )

    for pipeline in (s1, s2):
        stream = aiter(pipeline)
        first = await anext(stream)
        await stream.aclose()
        yield first


def print_results(result: Items) -> None:
    feed, count = result
    print(cast("dict", feed)["title"])
    print(cast("dict", count)["count"])


def main(*, test: bool = False) -> None:
    print_results(pipe(test=test))


if __name__ == "__main__":
    main()
