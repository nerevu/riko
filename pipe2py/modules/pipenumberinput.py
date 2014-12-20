# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipenumberinput
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=user_inputs#Number
"""

from pipe2py import util


def pipe_numberinput(context=None, _INPUT=None, conf=None, **kwargs):
    """An input that prompts the user for a number and yields it forever.
    Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : not used
    conf : {
        'name': {'value': 'parameter name'},
        'prompt': {'value': 'User prompt'},
        'default': {'value': 'default value'},
        'debug': {'value': 'debug value'}
    }

    Yields
    ------
    _OUTPUT : text
    """
    value = util.get_input(context, conf)

    try:
        value = int(value)
    except:
        value = 0

    while True:
        yield value
