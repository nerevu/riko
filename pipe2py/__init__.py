# pipe2py package
# Author: Greg Gaughan

# See LICENSE file for license details

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)


class Context(object):
    """The context of a pipeline
        verbose = debug printing during compilation and running
        describe_input = return pipe input requirements
        describe_dependencies = return a list of sub-pipelines used
        test = takes input values from default (skips the console prompt)
        inputs = a dictionary of values that overrides the defaults
            e.g. {'name one': 'test value1'}
    """
    def __init__(self, **kwargs):
        self.verbose = kwargs.get('verbose')
        self.test = kwargs.get('test')
        self.describe_input = kwargs.get('describe_input')
        self.describe_dependencies = kwargs.get('describe_dependencies')
        self.inputs = kwargs.get('inputs', {})
