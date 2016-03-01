# pipe2py modules package
# Author: Greg Gaughan

# Note: each module name must match the name used internally by Yahoo, preceded
# by pipe

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from functools import partial
from itertools import imap, repeat
from twisted.internet import defer as df
from pipe2py.lib import utils
from pipe2py.twisted import utils as tu
from pipe2py.lib.dotdict import DotDict

__sources__ = [
    # Source Modules
    'pipecsv',
    'pipefeedautodiscovery',
    'pipefetch',
    'pipefetchdata',
    'pipefetchpage',
    'pipefetchsitefeed',
    'pipeitembuilder',
    'piperssitembuilder',
    'pipexpathfetchpage',
    'pipeyql',
]

__inputs__ = [
    # User Input Modules
    'pipenumberinput',
    'pipeprivateinput',
    'pipetextinput',
    'pipeurlinput',
    # 'pipedateinput',
    # 'pipelocationinput',
    # 'pipeprivateinput',
]

__operators__ = [
    # Operator Modules
    'pipecount',
    'pipecreaterss',
    'pipefilter',
    'piperegex',
    'piperename',
    'pipereverse',
    'pipesort',
    'pipesplit',
    'pipesubelement',
    'pipetail',
    'pipetruncate',
    'pipeunion',
    'pipeuniq',
    # 'pipewebservice',
    # 'pipelocationextractor',
]

__loopings__ = [
    # URL Modules
    'pipeurlbuilder',

    # String Modules
    'pipeexchangerate',
    'pipehash',
    'pipestrconcat',
    'pipestrregex',
    'pipestrreplace',
    'pipestringtokenizer',
    'pipestrtransform',
    'pipesubstr',
    # 'pipetermextractor',
    # 'pipetranslate',
    # 'pipeyahooshortcuts',
    # 'pipestrprivate',

    # Date Modules
    'pipedatebuilder',
    'pipedateformat',

    # Location Modules
    # 'pipelocationbuilder',

    # Number Modules
    'pipesimplemath',
    'pipecurrencyformat',
]

__outputs__ = [
    # Output Modules
    'pipeoutput',
    # 'pipeoutputjson',
    # 'pipeoutputical',
    # 'pipeoutputkml',
    # 'pipeoutputcsv',
]

__all__ = __sources__ + __inputs__ + __operators__ + __loopings__ + __outputs__
_map_func = imap
_async_map_func = tu.asyncImap


def get_broadcast_funcs(pieces, ftype='with', async=False, **kwargs):
    test = kwargs.pop('pass_if', None)
    listize = kwargs.pop('listize', True)
    parse = kwargs.pop('parse', True)
    pdictize = kwargs.pop('pdictize', True)
    cust_func = kwargs.pop('cust_func', False)
    get_value = partial(utils.get_value, **kwargs)
    _get_with = partial(utils.get_with, **kwargs)
    _get_pass = partial(utils.get_pass, test=test)

    if parse:
        _get_func = partial(utils.parse_conf, parse_func=get_value, **kwargs)
        get_func = partial(df.maybeDeferred, _get_func) if async else _get_func
    else:
        get_func = partial(df.maybeDeferred, get_value) if async else get_value

    if listize:
        listed = utils.listize(pieces)
        piece_defs = map(DotDict, listed) if pdictize else listed
        map_func = _async_map_func if async else _map_func
        get_pieces = lambda item: map_func(get_func, piece_defs, repeat(item))
    else:
        piece_defs = DotDict(pieces) if pdictize else pieces
        get_pieces = partial(get_func, piece_defs)

    get_pass = partial(df.maybeDeferred, _get_pass) if async else _get_pass

    f = {
        'with': partial(df.maybeDeferred, _get_with) if async else _get_with,
        'pass': tu.asyncReturn if async else utils.passthrough,
        None: lambda _: tu.asyncNone if async else utils.passnone,
    }

    return filter(None, [get_pieces, f[ftype], get_pass, cust_func])


def get_dispatch_funcs(ftype='word', first=None, async=False):
    get_word, get_num = utils.get_word, utils.get_num
    passthrough = tu.asyncReturn if async else utils.passthrough

    f = {
        'word': partial(df.maybeDeferred, get_word) if async else get_word,
        'num': partial(df.maybeDeferred, get_num) if async else get_num,
        'pass': passthrough,
        None: lambda _: tu.asyncNone if async else utils.passnone,
    }

    return [first or passthrough, f[ftype], passthrough]


def get_split(item, pieces=None, async=False, **kwargs):
    dictize_input = kwargs.pop('dictize', False)
    funcs = get_broadcast_funcs(pieces, async=async, **kwargs)
    _input = DotDict(item) if item and dictize_input else item
    return [func(_input) for func in funcs]
