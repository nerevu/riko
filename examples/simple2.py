from pprint import pprint

from riko.collections import AsyncPipe, SyncPipe

p232_conf = {
    "attrs": [
        {"value": "www.google.com", "key": "link"},
        {"value": "google", "key": "title"},
        {"value": "empty", "key": "author"},
    ]
}

p421_conf = {"rule": [{"find": "empty", "param": "first", "replace": "ABC"}]}


def pipe(test=False):
    stream = SyncPipe("itembuilder", conf=p232_conf, test=test).strreplace(
        conf=p421_conf, field="author", assign="author"
    )

    return list(stream)


async def async_pipe(test=False):
    stream = await AsyncPipe("itembuilder", conf=p232_conf, test=test).strreplace(
        conf=p421_conf, field="author", assign="author"
    )

    return list(stream)


def print_results(result) -> None:
    for i in result:
        pprint(i)


def main(*, test: bool = False) -> None:
    print_results(pipe(test=test))


if __name__ == "__main__":
    main()
