from collections.abc import Awaitable
from pprint import pprint
from typing import overload

from riko.collections import AsyncPipe, SyncPipe

format_conf = {"type": "text", "input_key": "format", "test": True}
format_in = {"format": "%B %d, %Y"}
date_conf = {
    "type": "date",
    "default": "5/4/82",
    "prompt": "enter a date",
    "test": True,
}
dynamic_conf = {"format": {"terminal": "format", "path": "format"}}
build_conf = {
    "attrs": {"value": {"terminal": "formatted", "type": "text"}, "key": "date"}
}


def pipe(test=False):
    format_stream = SyncPipe("input", conf=format_conf, inputs=format_in)
    date_stream = SyncPipe("input", conf=date_conf)

    formatted = date_stream.dateformat(
        conf=dynamic_conf, format=format_stream, field="content", emit=True
    )

    stream = SyncPipe("itembuilder", conf=build_conf, formatted=formatted, test=test)
    return list(stream)


async def async_pipe(reactor, test=False):
    format_stream = AsyncPipe("input", conf=format_conf, inputs=format_in)
    date_stream = AsyncPipe("input", conf=date_conf)

    formatted = await date_stream.dateformat(
        conf=dynamic_conf, format=format_stream, field="content", emit=True
    )

    stream = await AsyncPipe(
        "itembuilder", conf=build_conf, formatted=formatted, test=test
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
