from pprint import pprint

from riko.bado import coroutine, return_value
from riko.collections import AsyncPipe, SyncPipe

p120_conf = {"type": "text"}
p120_inputs = {"format": "%B %d, %Y"}
p112_conf = {"type": "date", "default": "5/4/82", "prompt": "enter a date"}
p151_conf = {"format": {"terminal": "format", "path": "format"}}
p100_conf = {
    "attrs": {"value": {"terminal": "value", "path": "dateformat"}, "key": "date"}
}

p120_kwargs = {"conf": p120_conf, "inputs": p120_inputs, "assign": "format"}


def pipe(test=False):
    s1 = SyncPipe("input", test=test, **p120_kwargs)
    s2 = (
        SyncPipe("input", conf=p112_conf, test=test)
        # FIXME: dateformat no longer returns a struct_time
        .dateformat(conf=p151_conf, format=s1)
    )

    return SyncPipe("itembuilder", conf=p100_conf, value=s2, test=test).list


@coroutine
def async_pipe(reactor, test=False):
    s1 = yield AsyncPipe("input", test=test, **p120_kwargs)
    s2 = yield (
        AsyncPipe("input", conf=p112_conf, test=test).dateformat(
            conf=p151_conf, format=s1
        )
    )

    output_kwargs = {"conf": p100_conf, "value": s2, "test": test}
    output = yield (AsyncPipe("itembuilder", **output_kwargs).alist)
    return_value(output)


if __name__ == "__main__":
    for i in pipe():
        pprint(i)
