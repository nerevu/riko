from collections.abc import Awaitable, Mapping
from pprint import pprint
from typing import overload

from riko.collections import AsyncPipe, SyncPipe

p1_conf = {
    "attrs": [{"value": "http://www.caltrain.com/Fares/farechart.html", "key": "url"}]
}

p2_conf = {"rule": {"field": "url", "match": {"subkey": "url"}, "replace": "farechart"}}


def pipe(test=False):
    stream = SyncPipe("itembuilder", conf=p1_conf, test=test).regex(conf=p2_conf)
    return list(stream)


async def async_pipe(_, test=False):
    stream = await AsyncPipe("itembuilder", conf=p1_conf, test=test).regex(conf=p2_conf)

    return list(stream)


def print_results(result) -> None:
    for i in result:
        pprint(i["url"] if isinstance(i, Mapping) else i)


@overload
def main(*, test: bool = False) -> None: ...  # noqa: E704
@overload
def main(reactor, *, test: bool = False) -> Awaitable[None]: ...  # noqa: E704
def main(reactor=None, *, test: bool = False) -> None | Awaitable[None]:  # noqa: E302
    if reactor:

        async def run() -> None:
            print_results(await async_pipe(reactor, test=test))

        result = run()
    else:
        result = print_results(pipe(test=test))

    return result


if __name__ == "__main__":
    main()
