"""
Fetch freelance jobs, then drop duplicate links and PHP gigs.

Examples:

    Run it::

        run-pipe gigs

"""

from __future__ import annotations

from pprint import pprint
from typing import TYPE_CHECKING

from riko import Pipeline, get_path
from riko.types.modules import FetchDataConf, FilterConf, FilterConfRule, UniqConf

if TYPE_CHECKING:
    from riko.types import Item, Items

fetch_conf = FetchDataConf({"url": get_path("gigs.json"), "path": "value.items"})
uniq_conf = UniqConf({"uniq_key": "link"})
filter_conf = FilterConf(
    {
        "combine": "or",
        "permit": False,
        "rule": FilterConfRule(field="title", value="php", op="contains"),
    }
)


def build_pipeline() -> Pipeline:
    return (
        Pipeline.from_module("fetchdata", conf=fetch_conf)
        .uniq(conf=uniq_conf)
        .filter(conf=filter_conf)
    )


def pipe(test: bool = False) -> list[Item]:
    return list(build_pipeline())


def async_pipe(test: bool = False) -> Pipeline:
    return build_pipeline()


def print_results(result: Items) -> None:
    for i in result:
        pprint(i)


def main(*, test: bool = False) -> None:
    print_results(pipe(test=test))


if __name__ == "__main__":
    main()
