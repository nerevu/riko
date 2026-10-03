"""
Fetch freelance jobs, drop duplicate links and PHP gigs, then reverse-sort the rest.

Examples:

    Run it::

        run-pipe gigs

"""

from __future__ import annotations

from pprint import pprint
from typing import TYPE_CHECKING

from riko import Pipeline, get_path
from riko.types.modules import (
    FetchDataConf,
    FilterConf,
    FilterConfRule,
    SortConf,
    SortConfRule,
    UniqConf,
)

if TYPE_CHECKING:
    from riko.types import Item, Items

p1_conf = FetchDataConf({"url": get_path("gigs.json"), "path": "value.items"})
p2_conf = UniqConf({"uniq_key": "link"})
p3_conf = FilterConf(
    {
        "combine": "or",
        "permit": False,
        "rule": FilterConfRule(field="title", value="php", op="contains"),
    }
)

p4_conf = SortConf({"rule": SortConfRule(field="", dir="desc")})


def pipe(test: bool = False) -> list[Item]:
    flow = (
        Pipeline.from_module("fetchdata", conf=p1_conf)
        .uniq(conf=p2_conf)
        .filter(conf=p3_conf)
        .sort(conf=p4_conf)
    )

    return list(flow)


def async_pipe(test: bool = False) -> Pipeline:
    return (
        Pipeline.from_module("fetchdata", conf=p1_conf)
        .uniq(conf=p2_conf)
        .filter(conf=p3_conf)
        .sort(conf=p4_conf)
    )


def print_results(result: Items) -> None:
    for i in result:
        pprint(i)


def main(*, test: bool = False) -> None:
    print_results(pipe(test=test))


if __name__ == "__main__":
    main()
