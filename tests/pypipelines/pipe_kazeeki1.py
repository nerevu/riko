# vim: sw=4:ts=4:expandtab

from riko import Context
from riko.collections import SyncPipe
from riko.types.general import Conf
from tests.pypipelines._pipe_kazeeki import fetchdata_conf, regex_conf, rename_conf


def pipe_kazeeki1(
    item=None, conf: Conf = None, context: Context | None = None, **kwargs
):
    if context and context.describe_input:
        output = []
    elif context and context.describe_dependencies:
        output = ["fetchdata", "rename", "regex"]
    else:
        source = SyncPipe("fetchdata", context=context, conf=fetchdata_conf)
        output = source.rename(conf=rename_conf).regex(conf=regex_conf)

    return list(output)


if __name__ == "__main__":
    pipeline = pipe_kazeeki1(context=Context())

    for i in pipeline:
        print(i)
