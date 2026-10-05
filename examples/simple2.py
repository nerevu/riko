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
from riko.types.modules import (
    ItemBuilderConf,
    ParsedParam,
    StrReplaceConf,
    StrReplaceConfRule,
)

if TYPE_CHECKING:
    from riko.types import Item, Items

p232_conf = ItemBuilderConf(
    {
        "attrs": [
            ParsedParam({"value": "www.google.com", "key": "link"}),
            ParsedParam({"value": "google", "key": "title"}),
            ParsedParam({"value": "empty", "key": "author"}),
        ]
    }
)

p421_conf = StrReplaceConf(
    {"rule": StrReplaceConfRule(find="empty", param="first", replace="ABC")}
)

p421_options = {"field": "author", "assign": "author"}


def pipe(test: bool = False) -> list[Item]:
    pipeline = Pipeline.from_module("itembuilder", conf=p232_conf).strreplace(
        conf=p421_conf, options=p421_options
    )

    return list(pipeline)


def async_pipe(test: bool = False) -> Pipeline:
    return Pipeline.from_module("itembuilder", conf=p232_conf).strreplace(
        conf=p421_conf, options=p421_options
    )


def print_results(result: Items) -> None:
    for i in result:
        pprint(i)


def main(*, test: bool = False) -> None:
    print_results(pipe(test=test))


if __name__ == "__main__":
    main()
