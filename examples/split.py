from pprint import pprint

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


async def async_pipe(test=True):
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


def main(*, test: bool = False) -> None:
    print_results(pipe(test=test))


if __name__ == "__main__":
    main()
