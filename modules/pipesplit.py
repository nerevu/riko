# pipesplit.py
#
# (module contributed by https://github.com/tuukka, 2b62cf3a5d8408f7d0d8e3f332dcb19dcbca64bb)

from itertools import tee, imap
from copy import deepcopy

from pipe2py import util

class Split(object):
    def __init__(self, context, _INPUT, conf, splits=2, **kwargs):
        iterators = tee(_INPUT, splits)
        # deepcopy each item passed along so that changes in one branch
        # don't affect the other branch
        self.iterators = [imap(deepcopy, iterator) for iterator in iterators]

    def __iter__(self):
        return self.iterators.pop()

def pipe_split(context, _INPUT, conf, splits, **kwargs):
    """This operator splits a source into two identical copies.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:
    splits -- number of splits
    
    Yields (_OUTPUT, _OUTPUT2...):
    copies of all source items
    """
    
    return Split(context, _INPUT, conf, splits, **kwargs)
