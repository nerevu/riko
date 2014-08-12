# pipetextinput.py
#

from pipe2py import util


def pipe_textinput(context=None, _INPUT=None, conf=None, **kwargs):
    """This source prompts the user for some text and yields it forever.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- not used
    conf:
        name -- input parameter name
        default -- default
        prompt -- prompt

    Yields (_OUTPUT):
    text
    """
    value = util.get_input(context, conf)

    while True:
        yield value
