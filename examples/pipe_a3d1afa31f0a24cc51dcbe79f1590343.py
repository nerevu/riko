from riko import modules as mod
from riko.lib.collections import SyncPipe


def pipe_a3d1afa31f0a24cc51dcbe79f1590343(**kwargs):
    p163_conf = {'attrs':[{'value': 'http://www.caltrain.com/Fares/farechart.html', 'key': 'url'}]}
    p134_conf={'rule': [{'match': {'subkey': 'url'}, 'replace': 'fff'}]}

    p134 = (
        SyncPipe('itembuilder', conf=p163_conf)
            .pipe('regex', conf=p134_conf, **kwargs)
            .output)

    return p134



if __name__ == "__main__":
    for i in pipe_a3d1afa31f0a24cc51dcbe79f1590343():
        print i
