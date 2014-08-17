# pipesubstr.py
#

from pipe2py import util


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
    sfrom = int(util.get_value(conf['from'], None, **kwargs))
    length = int(util.get_value(conf['length'], None, **kwargs))

    for item in _INPUT:
        yield item[sfrom:sfrom+length]

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
