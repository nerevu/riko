# pipe2py modules package
# Author: Greg Gaughan

# Note: each module name must match the name used internally by Yahoo, preceded
# by pipe

from functools import partial
from itertools import imap, repeat
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict

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
    'pipetextinput',
    'pipeurlinput',
    'pipenumberinput',
    'pipeprivateinput',
    # 'pipedateinput',
    # 'pipelocationinput',
    # 'pipeprivateinput',

    # Operator Modules
    'pipefilter',
    'piperename',
    'piperegex',
    'pipeunion',
    'pipeloop',
    'pipesort',
    'pipecount',
    'pipetruncate',
    'pipereverse',
    'pipeuniq',
    'pipesubelement',
    'pipetail',
    'pipecreaterss',
    'pipesplit',
    # 'pipewebservice',
    # 'pipelocationextractor',

    # URL Modules
    'pipeurlbuilder',

    # String Modules
    'pipestrconcat',
    'pipestrregex',
    'pipesubstr',
    'pipestrreplace',
    'pipestringtokenizer',
    'pipestrtransform',
    'pipehash',
    'pipeexchangerate'
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


def get_broadcast_funcs(pieces, ftype='with', parse=True, **kwargs):
    test = kwargs.pop('pass_if', None)
    piece_defs = map(DotDict, utils.listize(pieces))
    get_value = partial(utils.get_value, **kwargs)
    get_pass = partial(utils.get_pass, test=test)

    if parse:
        parse_conf = partial(utils.parse_conf, parse_func=get_value, **kwargs)
    else:
        parse_conf = get_value

    get_pieces = lambda i: imap(parse_conf, piece_defs, repeat(i))

    f = {
        'with': partial(utils.get_with, **kwargs),
        'pass': utils.passthrough,
        None: utils.passnone
    }

    return [get_pieces, f[ftype], get_pass]
