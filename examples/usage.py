# vim: sw=4:ts=4:expandtab

"""
Builds two items with ``itembuilder`` and hashes each one.

Broader, doctested walkthroughs of riko's APIs live in ``README.rst``.

Examples:

    Run it::

        run-pipe usage

"""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko import Pipeline
from riko.types.modules import ItemBuilderConf, ParsedParam

if TYPE_CHECKING:
    from riko.types import Item

attrs = [
    ParsedParam({"key": "title", "value": "riko pt. 1"}),
    ParsedParam({"key": "content", "value": "Let's talk about riko!"}),
]

ib_conf = ItemBuilderConf({"attrs": attrs})


def pipe(test: bool = False) -> list[Item]:
    return list(Pipeline.from_module("itembuilder", conf=ib_conf).hash())


if __name__ == "__main__":
    for i in pipe():
        print(i)
