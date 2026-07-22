from collections.abc import Awaitable
from pprint import pprint
from typing import overload

from riko.collections import AsyncPipe, SyncPipe

p232_conf = {
    "attrs": [
        {"value": "www.google.com", "key": "link"},
        {"value": "google", "key": "title"},
        {"value": "empty", "key": "author"},
    ]
}

p421_conf = {"rule": [{"find": "empty", "param": "first", "replace": "ABC"}]}


def pipe(test=False):
    stream = SyncPipe("itembuilder", conf=p232_conf, test=test).strreplace(
        conf=p421_conf, field="author", assign="author"
    )

    return list(stream)


async def async_pipe(reactor, test=False):
    stream = await AsyncPipe("itembuilder", conf=p232_conf, test=test).strreplace(
        conf=p421_conf, field="author", assign="author"
    )

    return list(stream)


def print_results(result) -> None:
    for i in result:
        pprint(i)


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
