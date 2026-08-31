# vim: sw=4:ts=4:expandtab

"""
Builds two items with ``itembuilder`` and hashes each one.

Broader, doctested walkthroughs of riko's APIs live in ``README.rst``.

Examples:
    Run it::

        run-pipe usage

"""

from riko.collections import SyncPipe
from riko.types.modules import ItemBuilderConf, ParsedParam

attrs = [
    ParsedParam({"key": "title", "value": "riko pt. 1"}),
    ParsedParam({"key": "content", "value": "Let's talk about riko!"}),
]

ib_conf = ItemBuilderConf({"attrs": attrs})


def pipe(test=False):
    return SyncPipe("itembuilder", conf=ib_conf, test=test).hash()


if __name__ == "__main__":
    for i in pipe():
        print(i)
