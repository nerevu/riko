from collections.abc import Mapping
from pprint import pprint

from riko.collections import AsyncPipe, SyncPipe

p1_conf = {
    "attrs": [{"value": "http://www.caltrain.com/Fares/farechart.html", "key": "url"}]
}

p2_conf = {"rule": {"field": "url", "match": {"subkey": "url"}, "replace": "farechart"}}


def pipe(test=False):
    stream = SyncPipe("itembuilder", conf=p1_conf, test=test).regex(conf=p2_conf)
    return list(stream)


async def async_pipe(test=False):
    stream = await AsyncPipe("itembuilder", conf=p1_conf, test=test).regex(conf=p2_conf)

    return list(stream)


def print_results(result) -> None:
    for i in result:
        pprint(i["url"] if isinstance(i, Mapping) else i)


def main(*, test: bool = False) -> None:
    print_results(pipe(test=test))


if __name__ == "__main__":
    main()
