# vim: sw=4:ts=4:expandtab

from riko.collections import SyncPipe
from riko.context import Context
from tests.pypipelines._pipe_kazeeki import fetchdata_conf, regex_conf, rename_conf


def pipe(context: Context | None = None, **_):
    if context and context.describe_input:
        output = []
    elif context and context.describe_dependencies:
        output = ["fetchdata", "rename", "regex"]
    else:
        source = SyncPipe("fetchdata", context=context, conf=fetchdata_conf)
        output = source.rename(conf=rename_conf).regex(conf=regex_conf)

    return list(output)


if __name__ == "__main__":
    pipeline = pipe(context=Context())

    for i in pipeline:
        print(i)
