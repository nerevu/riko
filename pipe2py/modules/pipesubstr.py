# pipesubstr.py
#

from pipe2py.lib.dotdict import DotDict


def pipe_substr(context=None, _INPUT=None, conf=None, **kwargs):
    """Returns a substring.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- source generator
    conf:
        from -- starting character
        length -- number of characters to return

    Yields (_OUTPUT):
    portion of source string
    """
    conf = DotDict(conf)
    start = conf.get('from', func=int, **kwargs)
    length = conf.get('length', func=int, **kwargs)

    for item in _INPUT:
        yield item[start:start + length]

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
