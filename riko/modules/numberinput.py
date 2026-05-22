# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    riko.modules.numberinput
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=user_inputs#Number
"""

from functools import partial
from riko.modules.input import pipe as _pipe, async_pipe as _async_pipe

DEFAULTS = {"type": "int"}

"""An input that prompts the user for a number and yields it forever.
Not loopable.
"""
pipe = partial(_pipe, DEFAULTS)
async_pipe = partial(_async_pipe, DEFAULTS)
