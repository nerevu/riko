# pipesplit.py
#
# module contributed by https://github.com/tuukka

from itertools import tee, imap
from copy import deepcopy


class Split(object):
    def __init__(self, context, _INPUT, conf, splits=2, **kwargs):
        # todo? tee is not threadsafe
        # todo: is 2 iterators always enough?
        iterators = tee(_INPUT, splits)

        # deepcopy each item passed along so that changes in one branch
        # don't affect the other branch
        self.iterators = [imap(deepcopy, iterator) for iterator in iterators]

    def __iter__(self):
        try:
            return self.iterators.pop()
        except IndexError:
            raise ValueError("split has 2 outputs, tried to activate third")


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
