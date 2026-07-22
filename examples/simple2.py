from pprint import pprint

from riko.collections import AsyncPipe, SyncPipe
from riko.types.modules import (
    ItemBuilderConf,
    ParsedParam,
    StrReplaceConf,
    StrReplaceConfRule,
)

p232_conf = ItemBuilderConf(
    {
        "attrs": [
            ParsedParam({"value": "www.google.com", "key": "link"}),
            ParsedParam({"value": "google", "key": "title"}),
            ParsedParam({"value": "empty", "key": "author"}),
        ]
    }
)

p421_conf = StrReplaceConf(
    {"rule": StrReplaceConfRule(find="empty", param="first", replace="ABC")}
)


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
