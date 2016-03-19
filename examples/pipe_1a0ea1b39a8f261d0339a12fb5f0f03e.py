from riko import modules as mod
from riko.lib.collections import SyncPipe


def pipe_1a0ea1b39a8f261d0339a12fb5f0f03e(**kwargs):
    p385_conf = {'date': {'value': '12/2/2014'}}
    p405_conf = {'format': {'value': '%B %d, %Y'}}

    p393_conf = {
        'attrs': [
            {'value': {'terminal': 'attrs_1_value'}, 'key': {'value': 'date'}},
            {'value': '1201', 'key': 'year'}]}

    p405 = (
        SyncPipe('datebuilder', conf=p385_conf, **kwargs)
            .dateformat(conf=p405_conf, **kwargs)
            .output)


    p393 = (
        SyncPipe('itembuilder', conf=p393_conf, attrs_1_value=p405, **kwargs)
            .output)

    return p393


if __name__ == "__main__":
    for i in pipe_1a0ea1b39a8f261d0339a12fb5f0f03e():
        print i
