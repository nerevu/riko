# pipenumberinput.py
# vim: sw=4:ts=4:expandtab

from pipe2py import util


def pipe_numberinput(context=None, _INPUT=None, conf=None, **kwargs):
    """This source prompts the user for a number and yields it forever.

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

    try:
        value = int(value)
    except:
        value = 0

    while True:
        yield value
