#pipe2py package
#Author: Greg Gaughan

class Context(object):
    """The context of a pipeline
    
       verbose = debug printing during compilation and running
       
       describe_input = return pipe input requirements instead of running the pipe
       #todo: add describe_dependencies to return a list of sub-pipelines required

       test = use debug values for input prompts, i.e. for unit tests
       console = console is available for keyboard input
       inputs = a dictionary of input values to be used when console and test are False 
                e.g. {'name one': 'test value1'}
    """
    def __init__(self, verbose=False, describe_input=False, test=False, console=True, inputs=None):
        if inputs is None:
            inputs = {}
        self.verbose = verbose
        self.test = test
        self.console = console
        self.describe_input = describe_input
        self.inputs = inputs
