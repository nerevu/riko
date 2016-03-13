# Pipe testpipe1 generated by pipe2py

from pipe2py.modules import pipefetch
from pipe2py.modules import pipefilter
from pipe2py.modules.pipeoutput import pipe_output


def pipe_testpipe1(context=None, _INPUT=None, conf=None, **kwargs):
    # todo: insert pipeline description here
    conf = conf or {}

    if context and (context.describe_input or context.describe_dependencies):
        return []


    sw_90 = pipefetch.pipe(
        context=context, conf={'URL': {'type': 'url', 'value': 'file://data/feed.xml'}})

    sw_102 = pipefilter.pipe(
        sw_90, context=context, conf={'COMBINE': {'type': 'text', 'value': 'and'}, 'MODE': {'type': 'text', 'value': 'permit'}, 'RULE': [{'field': {'type': 'text', 'value': 'description'}, 'value': {'type': 'text', 'value': 'the'}, 'op': {'type': 'text', 'value': 'contains'}}]})

    _OUTPUT = pipe_output(context, sw_102, conf=[])

    return _OUTPUT


if __name__ == "__main__":
    pipeline = testpipe1()

    for i in pipeline:
        print i
