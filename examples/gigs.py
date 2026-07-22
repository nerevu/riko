from pprint import pprint

from riko import get_path
from riko.collections import AsyncPipe, SyncPipe

p1_conf = {"url": get_path("gigs.json"), "path": "value.items"}
p2_conf = {"uniq_key": "link"}
p3_conf = {
    "combine": "or",
    "permit": False,
    "rule": [{"field": "title", "value": "php", "op": "contains"}],
}

p4_conf = {"rule": [{"field": "pubDate", "dir": "desc"}]}


def pipe(test=False):
    stream = (
        SyncPipe("fetchdata", conf=p1_conf, test=test)
        .uniq(conf=p2_conf)
        .filter(conf=p3_conf)
        .sort(conf=p4_conf)
    )

    return list(stream)


async def async_pipe(test=False):
    stream = await (
        AsyncPipe("fetchdata", conf=p1_conf, test=test)
        .uniq(conf=p2_conf)
        .filter(conf=p3_conf)
        .sort(conf=p4_conf)
    )

    return list(stream)


def print_results(result) -> None:
    for i in result:
        pprint(i)


def main(*, test: bool = False) -> None:
    print_results(pipe(test=test))


if __name__ == "__main__":
    main()
