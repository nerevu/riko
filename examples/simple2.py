from pprint import pprint
from riko.bado import coroutine, return_value
from riko.collections import SyncPipe, AsyncPipe

p232_conf = {
    "attrs": [
        {"value": "www.google.com", "key": "link"},
        {"value": "google", "key": "title"},
        {"value": "empty", "key": "author"},
    ]
}

p421_conf = {"rule": [{"find": "empty", "param": "first", "replace": "ABC"}]}


def pipe(test=False):
    stream = (
        SyncPipe("itembuilder", conf=p232_conf, test=test)
        .strreplace(conf=p421_conf, field="author", assign="author")
        .list
    )

    return stream


@coroutine
def async_pipe(reactor, test=False):
    stream = yield (
        AsyncPipe("itembuilder", conf=p232_conf, test=test)
        .strreplace(conf=p421_conf, field="author", assign="author")
        .alist
    )

    return_value(stream)


if __name__ == "__main__":
    for i in pipe():
        pprint(i)
