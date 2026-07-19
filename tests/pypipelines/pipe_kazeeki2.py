# vim: sw=4:ts=4:expandtab


from riko import Context
from riko.collections import SyncPipe
from riko.types.general import Conf
from tests.pypipelines._pipe_kazeeki import itembuilder_conf, regex_conf, rename_conf


def pipe_kazeeki2(
    item=None, conf: Conf = None, context: Context | None = None, **kwargs
):
    if context and context.describe_input:
        output = []
    elif context and context.describe_dependencies:
        output = ["itembuilder", "rename", "regex"]
    else:
        source = SyncPipe("itembuilder", context=context, conf=itembuilder_conf)
        output = source.rename(conf=rename_conf).regex(conf=regex_conf)

    return list(output)


if __name__ == "__main__":
    pipeline = pipe_kazeeki2(context=Context())

    for i in pipeline:
        print(i)
