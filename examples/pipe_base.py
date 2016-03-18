from pipe import modules as mod
from pipe2py.lib.collections import SyncPipe


def pipe_base(**kwargs):
    p01_conf = {}

    p01 = (
    	SyncPipe('source', conf=p01_conf, **kwargs)
      		.output)

    return p01


if __name__ == "__main__":
    for i in pipe_base():
        print i
