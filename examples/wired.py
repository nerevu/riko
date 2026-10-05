"""
Wires one pipe's output into another's terminal.

A format ``input`` feeds a ``dateformat`` whose result is built into an item with
``itembuilder``.

Examples:

    Run it::

        run-pipe wired

"""

from __future__ import annotations

from pprint import pprint
from typing import TYPE_CHECKING

from riko import Pipeline, parse_dag
from riko.types.modules import (
    ConfArg,
    DateFormatRawConf,
    InputRawConf,
    ItemBuilderRawConf,
    Param,
)

if TYPE_CHECKING:
    from riko.types import Item, Items, PipeDag

in_test = ConfArg({"type": "bool", "value": "true"})
format_conf = InputRawConf(
    {
        "name": {"type": "text", "value": "format_input"},
        "prompt": {"type": "text", "value": "enter a date format"},
        "type": {"type": "text", "value": "text"},
        "default": {"type": "text", "value": "%B %d, %Y"},
        "test": in_test,
    }
)

date_conf = InputRawConf(
    {
        "name": {"type": "text", "value": "date_input"},
        "prompt": {"type": "text", "value": "enter a date"},
        "type": {"type": "text", "value": "date"},
        "default": {"type": "text", "value": "5/4/82"},
        "test": in_test,
    }
)
date_fmt_conf = DateFormatRawConf({"format": {"terminal": "format", "type": "text"}})
build_conf = ItemBuilderRawConf(
    {
        "attrs": Param(
            {
                "value": {"terminal": "formatted", "type": "text"},
                "key": {"type": "text", "value": "date"},
            }
        )
    }
)

dag: PipeDag = {
    "modules": [
        {"id": "format", "type": "input", "conf": format_conf},
        {"id": "date", "type": "input", "conf": date_conf},
        {
            "id": "formatted",
            "type": "dateformat",
            "conf": date_fmt_conf,
            "options": {"field": "content", "emit": True},
        },
        {"id": "build", "type": "itembuilder", "conf": build_conf},
    ],
    "wires": [
        ["format", "formatted", "in:format"],
        ["date", "formatted"],
        ["formatted", "build", "in:formatted"],
    ],
}


def pipe(test: bool = False) -> list[Item]:
    return list(Pipeline(parse_dag(dag)))


def async_pipe(test: bool = False) -> Pipeline:
    return Pipeline(parse_dag(dag))


def print_results(result: Items) -> None:
    for i in result:
        pprint(i)


def main(*, test: bool = False) -> None:
    print_results(pipe(test=test))


if __name__ == "__main__":
    main()
