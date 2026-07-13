# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    riko.modules.urlinput
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=user_inputs#URL
"""

from functools import partial
from riko.modules.input import pipe as _pipe, async_pipe as _async_pipe
from riko.types.general import Defaults

DEFAULTS: Defaults = {"type": "url"}

"""An input that prompts the user for a url and yields it forever.
Not loopable.
"""

pipe = partial(_pipe, defaults=DEFAULTS)
async_pipe = partial(_async_pipe, defaults=DEFAULTS)
