"""
Split one date input into long-form and year streams.

Fanning a stream out into independently consumable branches is not available yet,
so running this raises until that lands. The code shows the form it will take.

Examples:

    Run it::

        run-pipe split

"""

from __future__ import annotations

from pprint import pprint
from typing import TYPE_CHECKING, cast

from riko import Pipeline
from riko.types._enums import CastType
from riko.types.modules import DateFormatConf, InputConf

if TYPE_CHECKING:
    from riko.types import AsyncStream, Item, Items

long_conf = DateFormatConf({"format": "%B %d, %Y"})
year_conf = DateFormatConf({"format": "%Y"})
options = {"field": "content", "emit": True}


def pipe(test: bool = True) -> list[Item]:
    date_conf = InputConf({"type": CastType.DATE, "default": "12/2/2014", "test": test})

    date_source, year_source = Pipeline.from_module("input", conf=date_conf).split(2)
    date_stream = date_source.dateformat(conf=long_conf, options=options)
    year_stream = year_source.dateformat(conf=year_conf, options=options)
    year = next(iter(year_stream))
    return [{"date": next(iter(date_stream)), "year": int(cast("str", year))}]


async def async_pipe(test: bool = True) -> AsyncStream:
    date_conf = InputConf({"type": CastType.DATE, "default": "12/2/2014", "test": test})

    date_source, year_source = Pipeline.from_module("input", conf=date_conf).split(2)
    date_stream = date_source.dateformat(conf=long_conf, options=options)
    year_stream = year_source.dateformat(conf=year_conf, options=options)
    year = await anext(aiter(year_stream))
    date = await anext(aiter(date_stream))
    yield {"date": date, "year": int(cast("str", year))}


def print_results(result: Items) -> None:
    for i in result:
        pprint(i)


def main(*, test: bool = False) -> None:
    print_results(pipe(test=test))


if __name__ == "__main__":
    main()
