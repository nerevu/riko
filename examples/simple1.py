"""
Builds an item holding a URL, then rewrites it with ``regex``.

Examples:

    Run it::

        run-pipe simple1

"""

from __future__ import annotations

from collections.abc import Mapping
from pprint import pprint
from typing import TYPE_CHECKING

from riko import Pipeline
from riko.types.modules import ItemBuilderConf, RegexRawConf, RegexRawRule

if TYPE_CHECKING:
    from collections.abc import Iterable

    from riko.types import Item

p1_conf = ItemBuilderConf(
    {"attrs": [{"value": "http://www.caltrain.com/Fares/farechart.html", "key": "url"}]}
)

p2_conf = RegexRawConf(
    {
        "rule": RegexRawRule(
            {
                "field": {"type": "text", "value": "url"},
                "match": {"type": "text", "subkey": "url"},
                "replace": {"type": "text", "value": "farechart"},
            }
        )
    }
)


def pipe(test: bool = False) -> list[Item]:
    pipeline = Pipeline.from_module("itembuilder", conf=p1_conf).regex(conf=p2_conf)
    return list(pipeline)


def async_pipe(test: bool = False) -> Pipeline:
    return Pipeline.from_module("itembuilder", conf=p1_conf).regex(conf=p2_conf)


def print_results(result: Iterable[object]) -> None:
    for i in result:
        pprint(i["url"] if isinstance(i, Mapping) else i)


def main(*, test: bool = False) -> None:
    print_results(pipe(test=test))


if __name__ == "__main__":
    main()
