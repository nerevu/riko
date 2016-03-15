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
    'www.bbc.co.uk_news.html', 'edition.cnn.html', 'google_spreadsheet.csv',
    'yql.xml']

FEEDS = [
    'http://feeds.feedburner.com/TechCrunch/',
    'http://feeds.arstechnica.com/arstechnica/index']

FILES = ['file://%s' % p.join(parent, x) for x in parts]


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


def assign(item, assignment, key, one=False):
    value = assignment.next() if one else list(assignment)
    yield DotDict(cdicts(item, {key: value}))


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
                pipe2py.lib.dotdict.DotDict instance (default: True if either
                `extract` is False or both `listize` and `extract` are True)

            objectify (bool): Convert the `conf` to a
                pipe2py.lib.utils.Objectify instance (default: True).

            ptype (str): Used to convert `conf` items to a specific type.
                Performs conversion after obtaining the `objectify` value above.
                If set, objectified `conf` items will be converted upon
                attribute retrieval, and normal `conf` items will be converted
                immediately. Must be one of 'pass', 'none', 'text', or 'num'.
                Default: 'pass', i.e., return `conf` as is.

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

            assign (str): Attribute to assign output (default: 'content' if
                `ftype` is 'none', pipe name otherwise)

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
            >>> kwargs = {'conf':  {'times': 'three'}, 'assign': 'content'}
            >>> pipe(item, **kwargs).next()
            {u'content': u'say "hello world" three times!'}
            >>>
            >>> def run(reactor):
            ...     callback = lambda x: print(x.next())
            ...     d = asyncPipe(item, **kwargs)
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
            ...     'pdictize': False, 'emit': True, 'field': 'content', 'objectify': False}
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
            >>> kwargs = {'conf':  {'times': 'three'}, 'assign': 'content'}
            >>> pipe(item, **kwargs).next()
            {u'content': u'say "hello world" three times!'}
            >>>
            >>> def run(reactor):
            ...     callback = lambda x: print(x.next())
            ...     d = asyncPipe(item, **kwargs)
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
            module_name = wrapper.__module__.split('.')[-1].replace('pipe', '')
            wrapper.__dict__['name'] = module_name

            defaults = {
                'dictize': True, 'ftype': 'pass', 'ptype': 'pass',
                'objectify': True}

            combined = cdicts(self.defaults, defaults, self.opts, kwargs)
            is_source = combined['ftype'] == 'none'
            def_assign = 'content' if is_source else module_name
            extracted = 'extract' in combined
            pdictize = combined.get('listize') if extracted else True

            combined.setdefault('assign', def_assign)
            combined.setdefault('emit', is_source)
            combined.setdefault('pdictize', pdictize)
            conf = {k: combined[k] for k in self.defaults}
            conf.update(kwargs.get('conf', {}))
            combined.update({'conf': conf})

            # replace conf with dictized version so we can access its
            # attributes even if we already extracted a value
            updates = {'conf': DotDict(conf), 'assign': combined.get('assign')}
            kwargs.update(updates)

            item = item or {}
            _input = DotDict(item) if combined.get('dictize') else item
            bfuncs = get_broadcast_funcs(**combined)
            types = {combined['ftype'], combined['ptype']}

            if types.difference({'pass', 'none'}):
                dfuncs = get_dispatch_funcs(**combined)
            else:
                dfuncs = None

            parsed, orig_item = dispatch(_input, bfuncs, dfuncs=dfuncs)

            if self.async:
                r = pipe(*parsed, feed=orig_item, **kwargs)
                feed, skip = yield pipe(*parsed, feed=orig_item, **kwargs)
            else:
                feed, skip = pipe(*parsed, feed=orig_item, **kwargs)

            one, assignment = get_assignment(feed, skip, **combined)

            if skip or combined.get('emit'):
                output = assignment
            elif not skip:
                key = combined.get('assign')
                output = assign(_input, assignment, key, one=one)

            if self.async:
                returnValue(output)
            else:
                for o in output:
                    yield o

        is_source = self.opts.get('ftype') == 'none'
        wrapper.__dict__['type'] = 'processor'
        wrapper.__dict__['sub_type'] = 'source' if is_source else 'processor'
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
                pipe2py.lib.dotdict.DotDict instance (default: True if either
                `extract` is False or both `listize` and `extract` are True)

            objectify (bool):Convert `conf` to a pipe2py.lib.utils.Objectify
                instance (default: True).

            ptype (str): Used to convert `conf` items to a specific type.
                Performs conversion after obtaining the `objectify` value above.
                If set, objectified `conf` items will be converted upon
                attribute retrieval, and normal `conf` items will be converted
                immediately. Must be one of 'pass', 'none', 'text', or 'num'.
                Default: 'pass', i.e., return `conf` as is.

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

            assign (str): Attribute to assign output (default: the pipe name)

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
            >>> kwargs = {'conf':  {'times': 'three'}, 'assign': 'content'}
            >>> pipe1(items, **kwargs).next()
            {u'content': u'say "bye world" three times!'}
            >>> pipe2(items, **kwargs).next()
            {u'content': 4}
            >>>
            >>> @inlineCallbacks
            ... def run(reactor):
            ...     r1 = yield asyncPipe1(items, **kwargs)
            ...     print(r1.next())
            ...     r2 = yield asyncPipe2(items, **kwargs)
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
            >>> opts = {
            ...     'ftype': 'text', 'extract': 'times', 'listize': True,
            ...     'pdictize': False, 'emit': True, 'field': 'content', 'objectify': False}
            ...
            >>> @operator(**opts)
            ... def pipe1(feed, objconf, tuples, **kwargs):
            ...     for content, times in reversed(list(tuples)):
            ...         value = 'say "%s" %s times!' % (content, times[0])
            ...         yield {kwargs['assign']: value}
            ...
            >>> @operator(**opts)
            ... def pipe2(feed, objconf, tuples, **kwargs):
            ...     word_cnt = sum(len(content.split()) for content in feed)
            ...     return {kwargs['assign']: word_cnt}
            ...
            >>> # async pipes don't have to return a deffered,
            >>> # they work fine either way
            >>> @operator(async=True, **opts)
            ... def asyncPipe1(feed, objconf, tuples, **kwargs):
            ...     for content, times in reversed(list(tuples)):
            ...         value = 'say "%s" %s times!' % (content, times[0])
            ...         yield {kwargs['assign']: value}
            ...
            >>> # this is an admittedly contrived example to show how you would
            >>> # call an async function
            >>> @operator(async=True, **opts)
            ... @inlineCallbacks
            ... def asyncPipe2(feed, objconf, tuples, **kwargs):
            ...     words = (len(content.split()) for content in feed)
            ...     word_cnt = yield maybeDeferred(sum, words)
            ...     returnValue({kwargs['assign']: word_cnt})
            ...
            >>> items = [{'content': 'hello world'}, {'content': 'bye world'}]
            >>> kwargs = {'conf':  {'times': 'three'}, 'assign': 'content'}
            >>> pipe1(items, **kwargs).next()
            {u'content': u'say "bye world" three times!'}
            >>> pipe2(items, **kwargs).next()
            {u'content': 4}
            >>>
            >>> @inlineCallbacks
            ... def run(reactor):
            ...     r1 = yield asyncPipe1(items, **kwargs)
            ...     print(r1.next())
            ...     r2 = yield asyncPipe2(items, **kwargs)
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
            module_name = wrapper.__module__.split('.')[-1].replace('pipe', '')
            wrapper.__dict__['name'] = module_name

            defaults = {
                'dictize': True, 'ftype': 'pass', 'ptype': 'pass',
                'objectify': True, 'emit': True, 'assign': module_name}

            combined = cdicts(self.defaults, defaults, self.opts, kwargs)
            extracted = 'extract' in combined
            pdictize = combined.get('listize') if extracted else True

            combined.setdefault('pdictize', pdictize)
            conf = {k: combined[k] for k in self.defaults}
            conf.update(kwargs.get('conf', {}))
            combined.update({'conf': conf})

            # replace conf with dictized version so we can access its
            # attributes even if we already extracted a value
            updates = {'conf': DotDict(conf), 'assign': combined.get('assign')}
            kwargs.update(updates)

            items = items or iter([])
            _INPUT = imap(DotDict, items) if combined.get('dictize') else items
            bfuncs = get_broadcast_funcs(**combined)
            types = {combined['ftype'], combined['ptype']}

            if types.difference({'pass', 'none'}):
                dfuncs = get_dispatch_funcs(**combined)
            else:
                dfuncs = None

            pairs = (dispatch(item, bfuncs, dfuncs=dfuncs) for item in _INPUT)
            parsed, _ = dispatch(DotDict(), bfuncs, dfuncs=dfuncs)

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
                key = combined.get('assign')
                assigned = (assign({}, s, key, one=True) for s in singles)
                output = utils.multiplex(assigned)

            if self.async:
                returnValue(output)
            else:
                for o in output:
                    yield o

        wrapper.__dict__['type'] = 'operator'
        return inlineCallbacks(wrapper) if self.async else wrapper


def dispatch(item, bfuncs, dfuncs=None):
    split = utils.broadcast(item, *bfuncs)
    parsed = utils.dispatch(split, *dfuncs) if dfuncs else split
    return parsed, item


def get_broadcast_funcs(**kwargs):
    kw = utils.Objectify(kwargs, conf={})
    pieces = kw.conf[kw.extract] if kw.extract else kw.conf
    no_conf = remove_keys(kwargs, 'conf')

    if kw.listize:
        listed = utils.listize(pieces)
        piece_defs = map(DotDict, listed) if kw.pdictize else listed
        parser = partial(utils.parse_conf, **no_conf)
        pfuncs = [partial(parser, conf=conf) for conf in piece_defs]
        get_pieces = lambda item: utils.broadcast(item, *pfuncs)
    else:
        conf = DotDict(pieces) if kw.pdictize and pieces else pieces
        get_pieces = partial(utils.parse_conf, conf=conf, **no_conf)

    noop = partial(utils.cast, _type='none')
    gfunc = partial(utils.get_field, **kwargs)
    get_field = noop if kw.ftype == 'none' else gfunc
    return (get_field, get_pieces, partial(utils.get_skip, **kwargs))


def get_dispatch_funcs(**kwargs):
    pfunc =  partial(utils.cast, _type=kwargs['ptype'])
    field_dispatch = partial(utils.cast, _type=kwargs['ftype'])

    if kwargs['objectify']:
        piece_dispatch = lambda p: utils.Objectify(p.items(), func=pfunc)
    else:
        piece_dispatch = pfunc

    return [field_dispatch, piece_dispatch, partial(utils.cast, _type='pass')]

