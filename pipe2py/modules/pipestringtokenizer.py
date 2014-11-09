# pipestringtokenizer.py
#

from pipe2py.lib.dotdict import DotDict


def pipe_stringtokenizer(context=None, _INPUT=None, conf=None, **kwargs):
    """Splits a string into tokens delimited by separators.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:
        to-str -- separator string

    Yields (_OUTPUT):
    tokens of the input string
    """
    conf = DotDict(conf)
    delim = conf.get('to-str', **kwargs)

    for item in _INPUT:
        for chunk in item.split(delim):
            yield {'content': chunk}

        try:
            forever = item.get('forever')
        except AttributeError:
            forever = False

        if forever:
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
