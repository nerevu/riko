# pipeoutput.py
#


def pipe_output(context=None, _INPUT=None, conf=None, **kwargs):
    """This operator outputs the input source, i.e. does nothing.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:

    Yields (_OUTPUT):
    source items
    """
    # todo: convert back to XML or JSON
    for item in _INPUT:
        yield item
