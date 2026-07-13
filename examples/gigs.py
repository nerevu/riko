from pprint import pprint

from riko import get_path
from riko.bado import coroutine, return_value
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
        .list
    )

    return stream


@coroutine
def async_pipe(reactor, test=False):
    stream = yield (
        AsyncPipe("fetchdata", conf=p1_conf, test=test)
        .uniq(conf=p2_conf)
        .filter(conf=p3_conf)
        .sort(conf=p4_conf)
    )

    return_value(stream)


if __name__ == "__main__":
    for i in pipe():
        pprint(i)
