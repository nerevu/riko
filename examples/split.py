from pprint import pprint
from typing import cast

from riko.cast import CastType
from riko.collections import AsyncPipe, SyncPipe
from riko.types.modules import DateFormatConf, InputConf

date_conf = InputConf({"type": CastType.DATE})
date_in = {"content": "12/2/2014"}
long_conf = DateFormatConf({"format": "%B %d, %Y"})
year_conf = DateFormatConf({"format": "%Y"})


def pipe(test=True):
    kwargs = {"field": "content", "emit": True}
    date_source, year_source = SyncPipe(
        "input", conf=date_conf, inputs=date_in, test=test
    ).split()

    date_stream = SyncPipe("dateformat", source=date_source, conf=long_conf, **kwargs)
    year_stream = SyncPipe("dateformat", source=year_source, conf=year_conf, **kwargs)
    year = next(year_stream)
    return [{"date": next(date_stream), "year": int(cast(str, year))}]


async def async_pipe(test=True):
    kwargs = {"field": "content", "emit": True}
    date_source, year_source = await AsyncPipe(
        "input", conf=date_conf, inputs=date_in, test=test
    ).split()

    date_stream = await AsyncPipe(
        "dateformat", source=date_source, conf=long_conf, **kwargs
    )

    year_stream = await AsyncPipe(
        "dateformat", source=year_source, conf=year_conf, **kwargs
    )
    year = next(year_stream)
    return [{"date": next(date_stream), "year": int(cast(str, year))}]


def print_results(result) -> None:
    for i in result:
        pprint(i)


def main(*, test: bool = False) -> None:
    print_results(pipe(test=test))


if __name__ == "__main__":
    main()
