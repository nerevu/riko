#pipe2py package
#Author: Greg Gaughan

#See LICENSE file for license details


class Context(object):
    """The context of a pipeline
        verbose = debug printing during compilation and running

        describe_input = return pipe input requirements
        describe_dependencies = return a list of sub-pipelines used
        test = use debug values for input prompts, i.e. for unit tests
        console = console is available for keyboard input
        inputs = a dictionary of input values to be used when console and test
            are False (or submodule is True) e.g. {'name one': 'test value1'}
        submodule = take input from inputs because this is a submodule
    """
    def __init__(self, **kwargs):
        self.verbose = kwargs.get('verbose', False)
        self.test = kwargs.get('test', False)
        self.console = kwargs.get('console', True)
        self.describe_input = kwargs.get('describe_input', False)
        self.describe_dependencies = kwargs.get('describe_dependencies', False)
        self.inputs = kwargs.get('inputs', {})
        self.submodule = kwargs.get('submodule', False)
