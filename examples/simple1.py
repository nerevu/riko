from pprint import pprint

from riko.bado import coroutine, return_value
from riko.collections import AsyncPipe, SyncPipe

p1_conf = {
    "attrs": [{"value": "http://www.caltrain.com/Fares/farechart.html", "key": "url"}]
}

p2_conf = {"rule": {"field": "url", "match": {"subkey": "url"}, "replace": "farechart"}}


def pipe(test=False):
    stream = SyncPipe("itembuilder", conf=p1_conf, test=test).regex(conf=p2_conf).list
    return stream


@coroutine
def async_pipe(_, test=False):
    stream = yield (
        AsyncPipe("itembuilder", conf=p1_conf, test=test).regex(conf=p2_conf).alist
    )

    return_value(stream)


if __name__ == "__main__":
    for i in pipe():
        pprint(str(i["url"]))
