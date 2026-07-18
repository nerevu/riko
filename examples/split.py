from collections.abc import Awaitable
from pprint import pprint
from typing import overload

from riko.collections import AsyncPipe, SyncPipe

date_conf = {"type": "date"}
date_in = {"content": "12/2/2014"}
long_conf = {"format": "%B %d, %Y"}
year_conf = {"format": "%Y"}


def pipe(test=True):
    date_source, year_source = SyncPipe(
        "input", conf=date_conf, inputs=date_in, test=test
    ).split()

    date_stream = SyncPipe(
        "dateformat", source=date_source, field="content", conf=long_conf, emit=True
    )

    year_stream = SyncPipe(
        "dateformat", source=year_source, field="content", conf=year_conf, emit=True
    )

    return [{"date": next(date_stream), "year": int(next(year_stream))}]


async def async_pipe(reactor, test=True):
    date_source, year_source = await AsyncPipe(
        "input", conf=date_conf, inputs=date_in, test=test
    ).split()

    date_stream = await AsyncPipe(
        "dateformat", source=date_source, field="content", conf=long_conf, emit=True
    )

    year_stream = await AsyncPipe(
        "dateformat", source=year_source, field="content", conf=year_conf, emit=True
    )

    return [{"date": next(date_stream), "year": int(next(year_stream))}]


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
