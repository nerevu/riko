# vim: sw=4:ts=4:expandtab


from riko import Context
from riko.collections import SyncPipe
from tests.pypipelines._pipe_kazeeki import itembuilder_conf, regex_conf, rename_conf


def pipe_kazeeki2(context: Context | None = None):
    if context and context.describe_input:
        output = []
    elif context and context.describe_dependencies:
        output = ["itembuilder", "rename", "regex"]
    else:
        source = SyncPipe("itembuilder", context=context, conf=itembuilder_conf)
        output = source.rename(conf=rename_conf).regex(conf=regex_conf).list

    return output


if __name__ == "__main__":
    pipeline = pipe_kazeeki2(Context())

    for i in pipeline:
        print(i)
