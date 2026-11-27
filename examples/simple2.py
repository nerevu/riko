"""
Builds an item, then replaces a field's value with ``strreplace``.

Examples:

    Run it::

        run-pipe simple2

"""

from __future__ import annotations

from pprint import pprint
from typing import TYPE_CHECKING

from riko import Pipeline
from riko.types import CallOptions
from riko.types.modules import (
    ItemBuilderConf,
    ParsedParam,
    StrReplaceConf,
    StrReplaceConfRule,
)

if TYPE_CHECKING:
    from riko.types import Item, Items

build_conf = ItemBuilderConf(
    {
        "attrs": [
            ParsedParam({"value": "www.google.com", "key": "link"}),
            ParsedParam({"value": "google", "key": "title"}),
            ParsedParam({"value": "empty", "key": "author"}),
        ]
    }
)

replace_conf = StrReplaceConf(
    {"rule": StrReplaceConfRule(find="empty", param="first", replace="ABC")}
)

replace_options = CallOptions(field="author", assign="author")


def build_pipeline() -> Pipeline:
    return Pipeline.from_module("itembuilder", conf=build_conf).strreplace(
        conf=replace_conf, options=replace_options
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
