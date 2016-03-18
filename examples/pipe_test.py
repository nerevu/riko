from pipe import modules as mod
from pipe2py.lib.collections import SyncPipe


def pipe_testpipe(**kwargs):
    p90_conf = {'url': 'file://data/feed.xml'}
    p91_conf = {'COMBINE': 'and', 'MODE': 'permit', 'RULE': [{'field': 'description', 'value': 'the', 'op': 'contains'}]}

    p91 = (
    	SyncPipe('fetch', conf=p90_conf)
        	.filter(conf=p91_conf)
        	.output)

    return p91


if __name__ == "__main__":
    for i in testpipe():
        print i
