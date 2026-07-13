from pprint import pprint

from riko.bado import coroutine, return_value
from riko.collections import AsyncPipe, SyncPipe

p385_conf = {"type": "text"}
p385_in = {"content": "12/2/2014"}
p405_conf = {"format": "%B %d, %Y"}
p393_conf = {
    "attrs": [
        {"value": {"terminal": "date", "path": "dateformat"}, "key": "date"},
        {"value": {"terminal": "year", "path": "year"}, "key": "year"},
    ]
}

p385_kwargs = {"conf": p385_conf, "inputs": p385_in}


def pipe(test=True):
    stream = (
        SyncPipe("input", test=test, **p385_kwargs)
        # FIXME: dateformat no longer returns a struct_time
        .dateformat(conf=p405_conf)
        # .split()
        .list
    )

    print(stream)

    p393_kwargs = {"conf": p393_conf, "date": s1, "year": s2, "test": test}
    stream = SyncPipe("itembuilder", **p393_kwargs)
    return stream.list


@coroutine
def async_pipe(reactor, test=True):
    s1, s2 = yield (
        AsyncPipe("input", test=test, **p385_kwargs)
        .dateformat(conf=p405_conf)
        .split()
        .alist
    )

    p393_kwargs = {"conf": p393_conf, "date": s1, "year": s2, "test": test}
    stream = yield AsyncPipe("itembuilder", **p393_kwargs)
    return_value(stream.alist)


if __name__ == "__main__":
    for i in pipe():
        pprint(i)
