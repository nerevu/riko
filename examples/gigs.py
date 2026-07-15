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


async def async_pipe(reactor, test=False):
    stream = await (
        AsyncPipe("fetchdata", conf=p1_conf, test=test)
        .uniq(conf=p2_conf)
        .filter(conf=p3_conf)
        .sort(conf=p4_conf)
    )

    return list(stream)


if __name__ == "__main__":
    for i in pipe():
        pprint(i)
