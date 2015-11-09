# pipe2py modules package
# Author: Greg Gaughan

# Note: each module name must match the name used internally by Yahoo, preceded
# by pipe

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from functools import partial
from itertools import imap, repeat
from twisted.internet.defer import maybeDeferred, inlineCallbacks, returnValue
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict
from pipe2py.twisted.utils import asyncReturn, asyncNone, asyncBroadcast

__all__ = [
    # Source Modules
    'pipecsv',
    'pipefeedautodiscovery',
    'pipefetch',
    'pipefetchdata',
    'pipefetchpage',
    'pipefetchsitefeed',
    'pipeforever',
    'pipeitembuilder',
    'piperssitembuilder',
    'pipexpathfetchpage',
    'pipeyql',

    # User Input Modules
    'pipenumberinput',
    'pipeprivateinput',
    'pipetextinput',
    'pipeurlinput',
    # 'pipedateinput',
    # 'pipelocationinput',
    # 'pipeprivateinput',

    # Operator Modules
    'pipecount',
    'pipecreaterss',
    'pipefilter',
    'pipeloop',
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

    # Output Modules
    'pipeoutput',
    # 'pipeoutputjson',
    # 'pipeoutputical',
    # 'pipeoutputkml',
    # 'pipeoutputcsv',
]


def _get_broadcast_funcs(pieces, ftype='with', **kwargs):
    test = kwargs.pop('pass_if', None)
    listize = kwargs.pop('listize', True)
    parse = kwargs.pop('parse', True)
    pdictize = kwargs.pop('pdictize', True)
    cust_func = kwargs.pop('cust_func', False)
    get_value = partial(utils.get_value, **kwargs)
    get_pass = partial(utils.get_pass, test=test)
    get_with = partial(utils.get_with, **kwargs)

    if parse:
        get_func = partial(utils.parse_conf, parse_func=get_value, **kwargs)
    else:
        get_func = get_value

    if listize:
        listed = utils.listize(pieces)
        piece_defs = map(DotDict, listed) if pdictize else listed
        get_pieces = lambda item: imap(get_func, piece_defs, repeat(item))
    else:
        piece_defs = DotDict(pieces) if pdictize else pieces
        get_pieces = partial(get_func, piece_defs)

    return (get_pieces, get_with, get_pass, cust_func)


def get_async_broadcast_funcs(pieces, ftype='with', **kwargs):
    funcs = _get_broadcast_funcs(pieces, ftype, **kwargs)
    get_pieces, get_with, get_pass, cust_func = funcs

    f = {
        'with': partial(maybeDeferred, get_with),
        'pass': asyncReturn,
        None: lambda item: asyncNone
    }

    asyncGetPieces = partial(maybeDeferred, get_pieces)
    asyncGetPass = partial(maybeDeferred, get_pass)
    return filter(None, [asyncGetPieces, f[ftype], asyncGetPass, cust_func])


def get_broadcast_funcs(pieces, ftype='with', **kwargs):
    funcs = _get_broadcast_funcs(pieces, ftype, **kwargs)
    get_pieces, get_with, get_pass, cust_func = funcs
    f = {'with': get_with, 'pass': utils.passthrough, None: utils.passnone}
    return filter(None, [get_pieces, f[ftype], get_pass, cust_func])


def get_dispatch_funcs(ftype='word', first=utils.passthrough):
    f = {
        'word': utils.get_word,
        'num': utils.get_num,
        'pass': utils.passthrough,
        None: utils.passnone,
    }

    return [first, f[ftype], utils.passthrough]


def get_async_dispatch_funcs(ftype='word', first=asyncReturn):
    f = {
        'word': partial(maybeDeferred, utils.get_word),
        'num': partial(maybeDeferred, utils.get_num),
        'pass': asyncReturn,
        None: lambda item: asyncNone,
    }

    return [first, f[ftype], asyncReturn]


def get_splits(_INPUT, pieces=None, funcs=None, **kwargs):
    finitize = kwargs.pop('finitize', False)
    dictize = kwargs.pop('dictize', False)
    finite = utils.finitize(_INPUT) if finitize and _INPUT else _INPUT
    funcs = funcs or get_broadcast_funcs(pieces, **kwargs)
    inputs = imap(DotDict, finite) if finite and dictize else finite
    return utils.broadcast(inputs, *funcs) if inputs else funcs


@inlineCallbacks
def asyncGetSplits(_INPUT, pieces=None, funcs=None, **kwargs):
    _input = yield _INPUT
    finitize = kwargs.pop('finitize', False)
    dictize = kwargs.pop('dictize', False)
    # asyncDict = partial(maybeDeferred, DotDict)
    # inputs = yield asyncCmap(asyncDict, _input)
    finite = utils.finitize(_input) if finitize and _input else _input
    funcs = funcs or get_async_broadcast_funcs(pieces, **kwargs)
    inputs = imap(DotDict, finite) if finite and dictize else finite

    if inputs:
        result = yield asyncBroadcast(inputs, *funcs)
    else:
        result = yield asyncReturn(funcs)

    returnValue(result)
