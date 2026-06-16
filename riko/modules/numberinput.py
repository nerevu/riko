# vim: sw=4:ts=4:expandtab
"""
Provides functions for obtaining user input and parsing to a number.

http://pipes.yahoo.com/pipes/docs?doc=user_inputs#Number
"""

from functools import partial

from riko.modules.input import async_pipe as _async_pipe
from riko.modules.input import pipe as _pipe
from riko.types.general import Defaults

DEFAULTS: Defaults = {"type": "int"}

"""An input that prompts the user for a number and yields it forever.
Not loopable.
"""
pipe = partial(_pipe, defaults=DEFAULTS)
async_pipe = partial(_async_pipe, defaults=DEFAULTS)
