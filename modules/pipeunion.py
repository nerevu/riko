# pipeunion.py
#

from pipe2py import util

def pipe_union(_INPUT, conf, verbose=False, **kwargs):
    """This operator merges up to 5 source together.

    Keyword arguments:
    _INPUT -- source generator
    kwargs -- _OTHER1 - another source generator
              _OTHER2 etc.
    conf:
    
    Yields (_OUTPUT):
    union of all source items
    """
    
    #TODO the multiple sources should be pulled in parallel
    # check David Beazely for suggestions (co-routines with queues?)
    # or maybe use multiprocessing and Queues (perhaps over multiple servers too)
    #Single thread and sequentail pulling will do for now...
    
    for item in _INPUT:
        yield item
    
    for other in kwargs:
        if other.startswith('_OTHER'):
            for item in kwargs[other]:
                yield item
           
            
# Example use
if __name__ == '__main__':
    pass #todo