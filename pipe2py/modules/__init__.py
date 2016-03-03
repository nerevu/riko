# pipe2py modules package
# Author: Greg Gaughan

# Note: each module name must match the name used internally by Yahoo, preceded
# by pipe

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from functools import partial, wraps
from itertools import imap, repeat, chain
from operator import itemgetter

from twisted.internet import defer as df
from twisted.internet.defer import inlineCallbacks, maybeDeferred, returnValue

from pipe2py.lib import utils
from pipe2py.lib.log import Logger
from pipe2py.twisted import utils as tu
from pipe2py.lib.dotdict import DotDict
from pipe2py.lib.utils import combine_dicts as cdicts, remove_keys

logger = Logger(__name__).logger

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


def get_sync_funcs(**kwargs):
    # remove conf so a func can be called later with a conf keyword
    no_conf = remove_keys(kwargs, 'conf')

    funcs = {
        'text': utils.get_word,
        'num': utils.get_num,
        'pass': lambda item: item,
        'broadcast': utils.broadcast,
        'dispatch': utils.dispatch,
        'field': partial(utils.get_field, **kwargs),
        'conf': partial(utils.parse_conf, **no_conf),
        'params': partial(utils.parse_params, **no_conf),
        'value': partial(utils.get_value, **no_conf),
        'skip': partial(utils.get_skip, **kwargs),
        'partial': partial,
        None: lambda item: None,
    }

    return funcs


def get_async_funcs(**kwargs):
    # remove conf so a func can be called later with a conf keyword
    no_conf = remove_keys(kwargs, 'conf')

    funcs = {
        'text': tu.asyncPartial(utils.get_word),
        'num': tu.asyncPartial(utils.get_num),
        'pass': tu.asyncReturn,
        'broadcast': tu.asyncBroadcast,
        'dispatch': tu.asyncDispatch,
        'field': tu.asyncPartial(utils.get_field, **kwargs),
        'conf': tu.asyncPartial(utils.parse_conf, **no_conf),
        'params': tu.asyncPartial(utils.parse_params, **no_conf),
        'value': tu.asyncPartial(utils.get_value, **no_conf),
        'skip': tu.asyncPartial(utils.get_skip, **kwargs),
        'partial': tu.asyncPartial,
        None: lambda item: tu.asyncNone,
    }

    return funcs


def get_assignment(result, skip, **kwargs):
    # conf : {
    #     'assign': {'value': <assigned field name>},
    #     'count': {'value': <all or first>},
    # }
    result = iter(utils.listize(result))

    if skip:
        return None, result

    first_result = result.next()

    try:
        second_result = result.next()
    except StopIteration:
        # pipe delivers one result, e.g., strconcat
        result = chain([first_result], result)
        multiple = False
    else:
        # pipe delivers multiple results, e.g., fetchpage/tokenizer
        result = chain([first_result], [second_result], result)
        multiple = True

    first = kwargs.get('count') == 'first'
    one = first or not multiple
    return one, iter([first_result]) if one else result


def assign(item, assignment, one=False, **kwargs):
    value = assignment.next() if one else list(assignment)
    yield DotDict(cdicts(item, {kwargs['assign']: value}))


class processor(object):
    def __init__(self, defaults=None, async=False, **opts):
        """Creates a sync/async pipe that processes individual items

        Args:
            defaults (dict): The entry to process
            opts (dict): The keyword arguments passed to the wrapper

        Kwargs:
            context (obj): pipe2py.Context object
            conf (dict): The pipe configuration

        Examples:
            >>> from twisted.internet.defer import Deferred
            >>> from twisted.internet.task import react
            >>>
            >>> @processor()
            ... def pipe(item, objconf, skip, **kwargs):
            ...     if skip:
            ...         output = kwargs['feed']
            ...     else:
            ...         content = item['content']
            ...         output = 'say "%s" %s times!' % (content, objconf.times)
            ...
            ...     return output, skip
            ...
            >>> # this is an admittedly contrived example to show how you would
            >>> # call an async function
            >>> @processor(async=True)
            ... @inlineCallbacks
            ... def asyncPipe(item, objconf, skip, **kwargs):
            ...     if skip:
            ...         output = kwargs['feed']
            ...     else:
            ...         content = yield tu.asyncReturn(item['content'])
            ...         output = 'say "%s" %s times!' % (content, objconf.times)
            ...
            ...     result = output, skip
            ...     returnValue(result)
            ...
            >>> item = {'content': 'hello world'}
            >>> pipe(item, conf={'times': 'three'}).next()
            {u'content': u'say "hello world" three times!'}
            >>>
            >>> def run(reactor):
            ...     callback = lambda x: print(x.next())
            ...     d = asyncPipe(item, conf={'times': 'three'})
            ...     return d.addCallbacks(callback, logger.error)
            ...
            >>> try:
            ...     react(run, _reactor=tu.FakeReactor())
            ... except SystemExit:
            ...     pass
            ...
            {u'content': u'say "hello world" three times!'}
        """
        self.defaults = defaults or {}
        self.defaults.setdefault('assign', 'content')
        self.defaults.setdefault('count', 'all')
        self.opts = opts
        self.async = async

    def __call__(self, pipe):
        """Creates a sync/async pipe that processes individual items

        Args:
            defaults (dict): The entry to process
            opts (dict): The keyword arguments passed to the wrapper

        Kwargs:
            context (obj): pipe2py.Context object
            conf (dict): The pipe configuration

        Yields:
            dict: item

        Returns:
            Deferred: twisted.internet.defer.Deferred generator of items

        Examples:
            >>> from twisted.internet.defer import Deferred
            >>> from twisted.internet.task import react
            >>>
            >>> kwargs = {
            ...     'ftype': 'text', 'extract': 'times', 'listize': True,
            ...     'pdictize': False, 'emit': True}
            ...
            >>> @processor(**kwargs)
            ... def pipe(content, times, skip, **kwargs):
            ...     if skip:
            ...         output = kwargs['feed']
            ...     else:
            ...         value = 'say "%s" %s times!' % (content, times[0])
            ...         output = {kwargs['assign']: value}
            ...
            ...     return output, skip
            ...
            >>> # async pipes don't have to return a deffered,
            >>> # they work fine either way
            >>> @processor(async=True, **kwargs)
            ... def asyncPipe(content, times, skip, **kwargs):
            ...     if skip:
            ...         output = kwargs['feed']
            ...     else:
            ...         value = 'say "%s" %s times!' % (content, times[0])
            ...         output = {kwargs['assign']: value}
            ...
            ...     return output, skip
            ...
            >>> item = {'content': 'hello world'}
            >>> pipe(item, conf={'times': 'three'}).next()
            {u'content': u'say "hello world" three times!'}
            >>>
            >>> def run(reactor):
            ...     callback = lambda x: print(x.next())
            ...     d = asyncPipe(item, conf={'times': 'three'})
            ...     return d.addCallbacks(callback, logger.error)
            ...
            >>> try:
            ...     react(run, _reactor=tu.FakeReactor())
            ... except SystemExit:
            ...     pass
            ...
            {u'content': u'say "hello world" three times!'}
        """
        @wraps(pipe)
        def wrapper(item=None, **kwargs):
            combined = {
                    'dictize': True, 'pdictize': True, 'ftype': 'pass',
                    'objectify': True}

            combined.update(cdicts(self.defaults, self.opts, kwargs))
            combined.setdefault('parser', 'value' if combined.get('extract') else 'conf')
            kwargs.setdefault('assign', combined['assign'])
            combined['defaults'] = {k: v for k, v in combined.items() if k in self.defaults}
            item = item or {}
            _input = DotDict(item) if combined.get('dictize') else item

            if self.async:
                funcs = get_async_funcs(**combined)
            else:
                funcs = get_sync_funcs(**combined)

            bfuncs = get_broadcast_funcs(funcs, **combined)

            if combined['ftype'] != 'pass':
                dfuncs = get_dispatch_funcs(funcs, **combined)
            else:
                dfuncs = None

            kw = {'dfuncs': dfuncs, 'async': self.async}

            if self.async:
                asyncFunc = inlineCallbacks(dispatch)
                parsed, orig_item = yield asyncFunc(_input, funcs, bfuncs, **kw)
                r = pipe(*parsed, feed=orig_item, **kwargs)
                logger.debug(r)
                feed, skip = yield r
            else:
                parsed, orig_item = dispatch(_input, funcs, bfuncs, **kw).next()
                feed, skip = pipe(*parsed, feed=orig_item, **kwargs)

            one, assignment = get_assignment(feed, skip, **combined)

            if skip or combined.get('emit'):
                output = assignment
            elif not skip:
                output = assign(_input, assignment, one=one, **combined)

            if self.async:
                returnValue(output)
            else:
                for o in output:
                    yield o

        return inlineCallbacks(wrapper) if self.async else wrapper


def dispatch(item, funcs, bfuncs, dfuncs=None, async=False):
    if async:
        split = yield funcs['broadcast'](item, *bfuncs)
    else:
        split = funcs['broadcast'](item, *bfuncs)

    if dfuncs and async:
        parsed = yield funcs['dispatch'](split, *dfuncs)
    elif dfuncs:
        parsed = funcs['dispatch'](split, *dfuncs)
    else:
        parsed = split

    result = parsed, item

    if async:
        returnValue(result)
    else:
        yield result


def get_broadcast_funcs(funcs, **kwargs):
    kw = utils.Objectify(kwargs, conf={})
    pieces = kw.conf[kw.extract] if kw.conf and kw.extract else kw.conf

    if kw.listize:
        listed = utils.listize(pieces)
        piece_defs = map(DotDict, listed) if kw.pdictize else listed
        pfuncs = [funcs['partial'](funcs[kw.parser], conf=conf) for conf in piece_defs]
        get_pieces = lambda item: funcs['broadcast'](item, *pfuncs)
    else:
        conf = DotDict(pieces) if kw.pdictize else pieces
        get_pieces = funcs['partial'](funcs[kw.parser], conf=conf)

    return (funcs['field'], get_pieces, funcs['skip'])


def get_dispatch_funcs(funcs, **kwargs):
    return [funcs[kwargs.get('ftype')], funcs['pass'], funcs['pass']]
