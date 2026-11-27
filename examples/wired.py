"""
Wires one node's output stream into another node's terminal reference.

A format ``input`` feeds a ``dateformat`` whose result is built into an item with
``itembuilder``.

Examples:

    Run it::

        run-pipe wired

"""

from __future__ import annotations

from pprint import pprint
from typing import TYPE_CHECKING

from riko import Pipeline, Workflow
from riko.types.modules import (
    ConfArg,
    DateFormatRawConf,
    InputRawConf,
    ItemBuilderRawConf,
    Param,
)

if TYPE_CHECKING:
    from riko.types import Item, Items, PipeDag


def text(value: str) -> ConfArg:
    return ConfArg({"type": "text", "value": value})


def build_input_conf(name: str, prompt: str, kind: str, default: str) -> InputRawConf:
    return InputRawConf(
        {
            "name": text(name),
            "prompt": text(prompt),
            "type": text(kind),
            "default": text(default),
            "test": ConfArg({"type": "bool", "value": "true"}),
        }
    )


format_conf = build_input_conf(
    "format_input", "enter a date format", "text", "%B %d, %Y"
)
date_conf = build_input_conf("date_input", "enter a date", "date", "5/4/82")
date_fmt_conf = DateFormatRawConf({"format": {"terminal": "format", "type": "text"}})
build_conf = ItemBuilderRawConf(
    {
        "attrs": Param(
            {"value": {"terminal": "formatted", "type": "text"}, "key": text("date")}
        )
    }
)

dag: PipeDag = {
    "modules": [
        {"id": "format", "name": "input", "conf": format_conf},
        {"id": "date", "name": "input", "conf": date_conf},
        {
            "id": "formatted",
            "name": "dateformat",
            "conf": date_fmt_conf,
            "options": {"field": "content", "emit": True},
        },
        {"id": "build", "name": "itembuilder", "conf": build_conf},
    ],
    "wires": [
        ["format", "formatted", "in:format"],
        ["date", "formatted"],
        ["formatted", "build", "in:formatted"],
    ],
}


def build_pipeline() -> Pipeline:
    return Pipeline(Workflow.parse(dag))


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
