#pipe2py package
#Author: Greg Gaughan

class Context(object):
    """The context of a pipeline"""
    def __init__(self, verbose=False, test=False):
        self.verbose = verbose
        self.test = test
