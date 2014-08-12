# pipeurlinput.py
#

from pipe2py import util


def pipe_urlinput(context=None, _INPUT=None, conf=None, **kwargs):
    """This source prompts the user for a url and yields it forever.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- not used
    conf:
        name -- input parameter name
        default -- default
        prompt -- prompt

    Yields (_OUTPUT):
    url
    """
    value = util.get_input(context, conf)
    value = util.url_quote(value)

    while True:
        yield value
