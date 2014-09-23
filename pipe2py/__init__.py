#pipe2py package
#Author: Greg Gaughan

#See LICENSE file for license details


class Context(object):
    """The context of a pipeline
        verbose = debug printing during compilation and running
        describe_input = return pipe input requirements
        describe_dependencies = return a list of sub-pipelines used
        test = takes input values from default (skips the console prompt)
        inputs = a dictionary of values that overrides the defaults
            e.g. {'name one': 'test value1'}
        submodule = takes input values from inputs (or default)
    """
    def __init__(self, **kwargs):
        self.verbose = kwargs.get('verbose', False)
        self.test = kwargs.get('test', False)
        self.describe_input = kwargs.get('describe_input', False)
        self.describe_dependencies = kwargs.get('describe_dependencies', False)
        self.inputs = kwargs.get('inputs', {})
        self.submodule = kwargs.get('submodule', False)
