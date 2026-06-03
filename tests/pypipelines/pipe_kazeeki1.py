# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab

from riko import Context
from riko.collections import SyncPipe
from tests.pypipelines._pipe_kazeeki import fetchdata_conf, rename_conf, regex_conf


def pipe_kazeeki1(context: Context):
    if context and context.describe_input:
        output = []
    elif context and context.describe_dependencies:
        output = ["fetchdata", "rename", "regex"]
    else:
        source = SyncPipe("fetchdata", context=context, conf=fetchdata_conf)
        output = source.rename(conf=rename_conf).regex(conf=regex_conf).export()

    return output


if __name__ == "__main__":
    pipeline = pipe_kazeeki1(Context())

    for i in pipeline:
        print(i)
