# pipeunion.py
#

from pipe2py import util


def pipe_union(context=None, _INPUT=None, conf=None, **kwargs):
    """This operator merges up to 5 source together.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    kwargs -- _OTHER1 - another source generator
              _OTHER2 etc.

    Yields (_OUTPUT):
    union of all source items
    """

    #TODO the multiple sources should be pulled in parallel
    # check David Beazely for suggestions (co-routines with queues?)
    # or maybe use multiprocessing and Queues (perhaps over multiple servers too)
    #Single thread and sequential pulling will do for now...

    for item in _INPUT:
        #this is being fed forever, i.e. not a real source so just use _OTHERs
        if item == True:
            break

        yield item

    for other in kwargs:
        if other.startswith('_OTHER'):
            for item in kwargs[other]:
                yield item
