from pipe import modules as mod
from pipe2py.lib.collections import SyncPipe


def pipe_4f26297843f4952fad920af5990ddc50(**kwargs):
    p120_conf = {'type': 'text', 'default': '%B %d, %Y', 'prompt': 'enter date format', 'assign': 'format_input'}
    p124_conf = {'type': 'text', 'default': 'EST', 'prompt': 'enter time zone', 'assign': 'zone_input'}
    p112_conf = {'type': 'date', 'assign': 'data_input'}
    p151_conf = {'timezone': {'terminal': 'timezone'}, 'format': {'terminal': 'format'}}
    p100_conf = {'attrs': [{'value': {'terminal': 'attrs_1_value'}, 'key': {'value': 'date'}}]}

    p120 = mod.pipe_input.pipe(conf=p120_conf, **kwargs)
    p124 = mod.pipe_input.pipe(conf=p124_conf, **kwargs)

    p151 = (
        SyncPipe('input', conf=p112_conf, inputs={'data_input': '12/3/2014'}, **kwargs)
            .dateformat(timezone=p124, conf=p151_conf, format=p120, **kwargs)
            .output)

    p100 = (
        SyncPipe('itembuilder', conf=p100_conf, attrs_1_value=p151, **kwargs)
            .output)

    return p100


if __name__ == "__main__":
    for i in pipe_4f26297843f4952fad920af5990ddc50():
        print i
