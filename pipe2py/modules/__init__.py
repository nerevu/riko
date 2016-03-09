# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.modules
~~~~~~~~~~~~~~~
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from os import path as p
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
    'pipeprivateinput',
    'pipetextinput',
]

__aggregators__ = [
    # Aggregator Modules
    'pipecount',
    # 'pipemean',
    # 'pipemin',
    # 'pipemax',
    # 'pipesum',
]

__operators__ = [
    'pipefilter',
    'pipereverse',
    'pipesort',
    'pipesplit',
    'pipetail',
    'pipetruncate',
    'pipeunion',
    'pipeuniq',
    # 'pipewebservice',
]

__processors__ = [
    # 'pipecreaterss',
    'piperegex',
    'piperename',
    'pipesubelement',
    # 'pipelocationextractor',
    'pipenumberinput',
    'pipeurlinput',
    # 'pipedateinput',
    # 'pipelocationinput',
    # 'pipeprivateinput',
    'pipeurlbuilder',
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
    'pipedatebuilder',
    'pipedateformat',
    # 'pipelocationbuilder',
    'pipesimplemath',
    'pipecurrencyformat',
    'pipeoutput',
    # 'pipeoutputjson',
    # 'pipeoutputical',
    # 'pipeoutputkml',
    # 'pipeoutputcsv',
]

__all__ = __sources__ + __inputs__ + __operators__ + __processors__ + __aggregators__

parent = p.join(p.abspath(p.dirname(p.dirname(p.dirname(__file__)))), 'data')
parts = [
    'feed.xml', 'blog.ouseful.info_feed.xml', 'gigs.json', 'places.xml',
    'www.bbc.co.uk_news.html', 'edition.cnn.html', 'google_spreadsheet.csv']

FEEDS = [
    'http://feeds.feedburner.com/TechCrunch/',
    'http://feeds.arstechnica.com/arstechnica/index']

FILES = ['file://%s' % p.join(parent, x) for x in parts]


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
        'none': lambda item: None,
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
        'none': lambda item: tu.asyncNone,
    }

    return funcs


def get_assignment(result, skip, **kwargs):
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

            defaults (dict): Default `conf` values.
            async (bool): Wrap an async pipe (default: False)
            opts (dict): The keyword arguments passed to the wrapper

        Kwargs:
            context (obj): The pipe context (a pipe2py.Context object)
            conf (dict): The pipe configuration
            extract (str): The key with which to get a value from `conf`. If set,
                the wrapped pipe will receive this value instead of `conf`
                (default: None).

            listize (bool): Ensure that the value returned from an `extract` is
                list-like (default: False)

            pdictize (bool): Convert `conf` or an `extract` to a
                pipe2py.lib.dotdict.DotDict instance (default: True)

            objectify (bool):Convert `conf` to a pipe2py.lib.utils.Objectify
                instance (default: True, ignored unless `parser` is set to
                'conf').

            parser (str): The `conf` parse function. Must be one of 'conf',
                'value', or 'params' (default: 'value' if `extract` is set else
                'conf')

            dictize (bool): Convert the input `item` to a DotDict instance
                (default: True)

            field (str): The key with which to get a value from the input
                `item`. If set, the wrapped pipe will receive this value
                instead of `item` (default: None).

            ftype (str): Used to convert the input `item` to a specific type.
                Performs conversion after obtaining the `field` value above.
                If set, the wrapped pipe will receive this value instead of
                `item`. Must be one of 'pass', 'none', 'text', or 'num' (
                default: 'pass', i.e., return the item as is)

            count (str): Output count. Must be either 'first' or 'all'
                (default: 'all', i.e., output all results).

            assign (str): Attribute to assign output (default: content)

            emit (bool): Return the output as is and don't assign it to an item
                attribute (default: False).

            skip_if (func): A function that takes the `item` and should return
                True if processing should be skipped, or False otherwise. If
                processing is skipped, the resulting output will be the original
                input `item`.

        Examples:
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

            if combined['ftype'] not in {'pass', 'none'}:
                dfuncs = get_dispatch_funcs(funcs, **combined)
            else:
                dfuncs = None

            kw = {'dfuncs': dfuncs, 'async': self.async}

            if self.async:
                asyncFunc = inlineCallbacks(dispatch)
                parsed, orig_item = yield asyncFunc(_input, funcs, bfuncs, **kw)
                r = pipe(*parsed, feed=orig_item, **kwargs)
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

        wrapper.__dict__ = {
            'type': 'processor',
            'sub_type': 'source' if self.opts.get('ftype') == 'none' else 'processor'}

        return inlineCallbacks(wrapper) if self.async else wrapper


class operator(object):
    def __init__(self, defaults=None, async=False, **opts):
        """Creates a sync/async pipe that processes an entire feed of items

        Args:
            defaults (dict): Default `conf` values.
            async (bool): Wrap an async pipe (default: False)
            opts (dict): The keyword arguments passed to the wrapper

        Kwargs:
            context (obj): The pipe context (a pipe2py.Context object)
            conf (dict): The pipe configuration
            extract (str): The key with which to get values from `conf`. If set,
                the wrapped pipe will receive these value instead of `conf`
                (default: None).

            listize (bool): Ensure that the value returned from an `extract` is
                list-like (default: False)

            pdictize (bool): Convert `conf` or an `extract` to a
                pipe2py.lib.dotdict.DotDict instance (default: True)

            objectify (bool):Convert `conf` to a pipe2py.lib.utils.Objectify
                instance (default: True, ignored unless `parser` is set to
                'conf').

            parser (str): The `conf` parse function. Must be one of 'conf',
                'value', or 'params' (default: 'value' if `extract` is set else
                'conf')

            dictize (bool): Convert the input `items` to DotDict instances
                (default: True)

            field (str): The key with which to get values from the input
                `items`. If set, the wrapped pipe will receive these values
                instead of `items` (default: None).

            ftype (str): Used to convert the input `items` to a specific type.
                Performs conversion after obtaining the `field` values above.
                If set, the wrapped pipe will receive these values instead of
                `items`. Must be one of 'pass', 'none', 'text', or 'num' (
                default: 'pass', i.e., return the item as is)

            count (str): Output count. Must be either 'first' or 'all'
                (default: 'all').

            assign (str): Attribute to assign output (default: content)

            emit (bool): return the output as is and don't assign it to an item
                attribute (default: True).

        Examples:
            >>> from twisted.internet.task import react
            >>>
            >>> # emit is True by default
            >>> # and operators can't skip items, so the pipe is passed an
            >>> # item dependent version of objconf as the 3rd arg
            >>> @operator(emit=False)
            ... def pipe1(feed, objconf, tuples, **kwargs):
            ...     for item, objconf in reversed(list(tuples)):
            ...         yield 'say "%s" %s times!' % (item['content'], objconf.times)
            ...
            >>> @operator(emit=False)
            ... def pipe2(feed, objconf, tuples, **kwargs):
            ...     return sum(len(item['content'].split()) for item in feed)
            ...
            >>> # this is an admittedly contrived example to show how you would
            >>> # call an async function
            >>> @operator(async=True, emit=False)
            ... @inlineCallbacks
            ... def asyncPipe1(feed, objconf, tuples, **kwargs):
            ...     for item, objconf in reversed(list(tuples)):
            ...         content = yield tu.asyncReturn(item['content'])
            ...         value = 'say "%s" %s times!' % (content, objconf.times)
            ...         returnValue(value)
            ...
            >>> # async pipes don't have to return a deffered,
            >>> # they work fine either way
            >>> @operator(async=True, emit=False)
            ... def asyncPipe2(feed, objconf, tuples, **kwargs):
            ...     return sum(len(item['content'].split()) for item in feed)
            ...
            >>> items = [{'content': 'hello world'}, {'content': 'bye world'}]
            >>> pipe1(items, conf={'times': 'three'}).next()
            {u'content': u'say "bye world" three times!'}
            >>> pipe2(items, conf={'times': 'three'}).next()
            {u'content': 4}
            >>>
            >>> @inlineCallbacks
            ... def run(reactor):
            ...     r1 = yield asyncPipe1(items, conf={'times': 'three'})
            ...     print(r1.next())
            ...     r2 = yield asyncPipe2(items, conf={'times': 'three'})
            ...     print(r2.next())
            ...
            >>> try:
            ...     react(run, _reactor=tu.FakeReactor())
            ... except SystemExit:
            ...     pass
            ...
            {u'content': u'say "bye world" three times!'}
            {u'content': 4}
        """
        self.defaults = defaults or {}
        self.defaults.setdefault('assign', 'content')
        self.defaults.setdefault('count', 'all')
        logger.debug(defaults)
        self.opts = opts
        self.async = async

    def __call__(self, pipe):
        """Creates a sync/async pipe that processes an entire feed of items

        Args:
            defaults (dict): The entry to process
            opts (dict): The keyword arguments passed to the wrapper

        Kwargs:
            context (obj): pipe2py.Context object
            conf (dict): The pipe configuration

        Yields:
            dict: twisted.internet.defer.Deferred item with feeds

        Examples:
            >>> from twisted.internet.task import react
            >>>
            >>> kwargs = {
            ...     'ftype': 'text', 'extract': 'times', 'listize': True,
            ...     'pdictize': False, 'emit': True}
            ...
            >>> @operator(**kwargs)
            ... def pipe1(feed, objconf, tuples, **kwargs):
            ...     for content, times in reversed(list(tuples)):
            ...         value = 'say "%s" %s times!' % (content, times[0])
            ...         yield {kwargs['assign']: value}
            ...
            >>> @operator(**kwargs)
            ... def pipe2(feed, objconf, tuples, **kwargs):
            ...     word_cnt = sum(len(content.split()) for content in feed)
            ...     return {kwargs['assign']: word_cnt}
            ...
            >>> # async pipes don't have to return a deffered,
            >>> # they work fine either way
            >>> @operator(async=True, **kwargs)
            ... def asyncPipe1(feed, objconf, tuples, **kwargs):
            ...     for content, times in reversed(list(tuples)):
            ...         value = 'say "%s" %s times!' % (content, times[0])
            ...         yield {kwargs['assign']: value}
            ...
            >>> # this is an admittedly contrived example to show how you would
            >>> # call an async function
            >>> @operator(async=True, **kwargs)
            ... @inlineCallbacks
            ... def asyncPipe2(feed, objconf, tuples, **kwargs):
            ...     words = (len(content.split()) for content in feed)
            ...     word_cnt = yield maybeDeferred(sum, words)
            ...     returnValue({kwargs['assign']: word_cnt})
            ...
            >>> items = [{'content': 'hello world'}, {'content': 'bye world'}]
            >>> conf = {'times': 'three'}
            >>> pipe1(items, conf=conf).next()
            {u'content': u'say "bye world" three times!'}
            >>> pipe2(items, conf=conf).next()
            {u'content': 4}
            >>>
            >>> @inlineCallbacks
            ... def run(reactor):
            ...     r1 = yield asyncPipe1(items, conf=conf)
            ...     print(r1.next())
            ...     r2 = yield asyncPipe2(items, conf=conf)
            ...     print(r2.next())
            ...
            >>> try:
            ...     react(run, _reactor=tu.FakeReactor())
            ... except SystemExit:
            ...     pass
            ...
            {u'content': u'say "bye world" three times!'}
            {u'content': 4}
        """
        @wraps(pipe)
        def wrapper(items=None, **kwargs):
            combined = {
                'dictize': True, 'pdictize': True, 'ftype': 'pass',
                'objectify': True, 'emit': True}

            combined.update(cdicts(self.defaults, self.opts, kwargs))
            combined.setdefault('parser', 'value' if combined.get('extract') else 'conf')
            kwargs.setdefault('assign', combined['assign'])
            combined['defaults'] = {k: v for k, v in combined.items() if k in self.defaults}
            items = items or iter([])
            _INPUT = imap(DotDict, items) if combined.get('dictize') else items

            if self.async:
                funcs = get_async_funcs(**combined)
            else:
                funcs = get_sync_funcs(**combined)

            bfuncs = get_broadcast_funcs(funcs, **combined)

            # replace conf with dictized version so we can access its
            # attributes even if we already extracted a value
            conf = combined['defaults']
            conf.update(kwargs.get('conf', {}))
            kwargs.update({'conf': DotDict(conf)})

            if combined['ftype'] not in {'pass', 'none'}:
                dfuncs = get_dispatch_funcs(funcs, **combined)
            else:
                dfuncs = None

            kw = {'dfuncs': dfuncs, 'async': self.async}
            args = (funcs, bfuncs)

            if self.async:
                asyncFunc = inlineCallbacks(dispatch)
                pairs = yield tu.asyncImap(lambda i: asyncFunc(i, *args, **kw), _INPUT)
                parsed, _ = yield asyncFunc({}, funcs, bfuncs, **kw)
            else:
                pairs = (dispatch(item, *args, **kw).next() for item in _INPUT)
                parsed, _ = dispatch(DotDict(), funcs, bfuncs, **kw).next()

            # - operators can't skip items
            # - purposely setting both variables to maps of the same iterable
            #   since only one is intended to be used at any given time
            # - `tuples` is an iterator of tuples of the first two `parsed`
            #   elements
            tuples = ((p[0][0], p[0][1]) for p in pairs)
            orig_feed = (p[0][0] for p in pairs)
            objconf = parsed[1]

            if self.async:
                feed = yield pipe(orig_feed, objconf, tuples, **kwargs)
            else:
                feed = pipe(orig_feed, objconf, tuples, **kwargs)

            sub_type = 'aggregator' if hasattr(feed, 'keys') else 'operator'
            wrapper.__dict__['sub_type'] = sub_type

            # operators can only assign one value per item and can't skip items
            _, assignment = get_assignment(feed, False, **combined)

            if combined.get('emit'):
                output = assignment
            else:
                singles = (iter([v]) for v in assignment)
                assigned = (assign({}, s, one=True, **combined) for s in singles)
                output = utils.multiplex(assigned)

            if self.async:
                returnValue(output)
            else:
                for o in output:
                    yield o

        wrapper.__dict__['type'] = 'operator',
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
    kw = utils.Objectify(kwargs, conf=kwargs['defaults'])
    pieces = kw.conf[kw.extract] if kw.extract else kw.conf

    if kw.listize:
        listed = utils.listize(pieces)
        piece_defs = map(DotDict, listed) if kw.pdictize else listed
        pfuncs = [funcs['partial'](funcs[kw.parser], conf=conf) for conf in piece_defs]
        get_pieces = lambda item: funcs['broadcast'](item, *pfuncs)
    else:
        conf = DotDict(pieces) if kw.pdictize and pieces else pieces
        get_pieces = funcs['partial'](funcs[kw.parser], conf=conf)

    get_field = funcs['none'] if kw.ftype == 'none' else funcs['field']
    return (get_field, get_pieces, funcs['skip'])


def get_dispatch_funcs(funcs, **kwargs):
    return [funcs[kwargs.get('ftype')], funcs['pass'], funcs['pass']]
