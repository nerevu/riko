from pprint import pprint

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


def pipe(test=True):
    s1, s2 = (
        SyncPipe("input", test=test, conf=p385_conf, inputs=p385_in)
        # FIXME: dateformat no longer returns a struct_time
        .dateformat(conf=p405_conf)
    )

    p393_kwargs = {"conf": p393_conf, "date": s1, "year": s2, "test": test}
    stream = SyncPipe("itembuilder", **p393_kwargs)
    return list(stream)


async def async_pipe(reactor, test=True):
    s1, s2 = await (
        AsyncPipe("input", test=test, conf=p385_conf, inputs=p385_in)
        .dateformat(conf=p405_conf)
        .split()
    )

    p393_kwargs = {"conf": p393_conf, "date": s1, "year": s2, "test": test}
    stream = await AsyncPipe("itembuilder", **p393_kwargs)
    return list(stream)


if __name__ == "__main__":
    for i in pipe():
        pprint(i)
