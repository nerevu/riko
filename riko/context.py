# vim: sw=4:ts=4:expandtab
"""
riko.context
~~~~~~~~~~~~
The execution context for a pipeline.
"""


class Context:
    """
    The context of a pipeline
    verbose = debug printing during compilation and running
    describe_input = return pipe input requirements
    describe_dependencies = return a list of sub-pipelines used
    test = takes input values from default (skips the console prompt)
    inputs = a dictionary of values that overrides the defaults
        e.g. {'name one': 'test value1'}
    submodule = takes input values from inputs (or default)
    """

    def __init__(self, **kwargs):
        self.verbose = bool(kwargs.get("verbose"))
        self.test = bool(kwargs.get("test"))
        self.describe_input = bool(kwargs.get("describe_input"))
        self.describe_dependencies = bool(kwargs.get("describe_dependencies"))
        self.inputs = dict(kwargs.get("inputs") or {})
        self.submodule = kwargs.get("submodule", False)

    def __repr__(self):
        content = f"verbose={self.verbose}, test={self.test}, "
        content += f"describe_input={self.describe_input}, "
        content += f"describe_dependencies={self.describe_dependencies}, "
        content += f"inputs={self.inputs}, submodule={self.submodule}"
        return f"Context({content})"


__all__ = ["Context"]
