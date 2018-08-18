# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules
~~~~~~~~~~~~
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from functools import partial, wraps
from itertools import chain

from builtins import iter, list, map, next

from riko.bado import coroutine, return_value
from riko.cast import cast
from riko.utils import multiplex, broadcast, dispatch
from riko.parsers import parse_conf, get_skip, get_field
from riko.dotdict import DotDict
from meza.fntools import remove_keys, listize, Objectify
from meza.process import merge

logger = gogo.Gogo(__name__, monolog=True).logger

__sources__ = [
    'csv',
    'feedautodiscovery',
    'fetch',
    'fetchdata',
    'fetchpage',
    'fetchsitefeed',
    'itembuilder',
    'rssitembuilder',
    'xpathfetchpage',
    'yql',
    'input',
]

__aggregators__ = [
    'count',
    'sum',
    # 'mean',
    # 'min',
    # 'max',
]

__composers__ = [
    'filter',
    'reverse',
    'sort',
    'split',
    'tail',
    'truncate',
    'union',
    'uniq',
    # 'webservice',
]

__transformers__ = [
    'currencyformat',
    'dateformat',
    'exchangerate',
    'hash',
    # 'locationextractor',
    # 'outputcsv',
    # 'outputical',
    # 'outputjson',
    # 'outputkml',
    'regex',
    'rename',
    'refind',
    'simplemath',
    'slugify',
    'strconcat',
    'strfind',
    'strreplace',
    'strtransform',
    'subelement',
    'substr',
    # 'termextractor',
    'tokenizer',
    # 'translate',
    'urlbuilder',
    'urlparse',
    # 'yahooshortcuts',
]

__all__ = __sources__ + __composers__ + __transformers__ + __aggregators__


def get_assignment(result, skip=False, **kwargs):
    # print(result)
    result = iter(listize(result))

    if skip:
        return None, result

    first_result = next(result)

    try:
        second_result = next(result)
    except StopIteration:
        # pipe delivers one result, e.g., strconcat
        result = chain([first_result], result)
        multiple = False
    else:
        # pipe delivers multiple results, e.g., fetchpage/tokenizer
        result = chain([first_result], [second_result], result)
        multiple = True

    first = kwargs.get('count') == 'first'
    _all = kwargs.get('count') == 'all'
    one = first or not (multiple or _all)
    return one, iter([first_result]) if one else result


def assign(item, assignment, **kwargs):
    key = kwargs.get('assign')
    value = next(assignment) if kwargs.get('one') else list(assignment)
    merged = merge([item, {key: value}])
    yield DotDict(merged) if kwargs.get('dictize') else merged


class processor(object):
    def __init__(self, defaults=None, isasync=False, debug=False, **opts):
        """Creates a sync/async pipe that processes individual items. These
        pipes are classified as `type: processor` and as either
        `sub_type: transformer` or `subtype: source`. To be recognized as
        `subtype: source`, the pipes `ftype` must be set to 'none'.

        Args:
            defaults (dict): Default `conf` values.
            async (bool): Wrap an async pipe (default: False)
            debug (bool): Print pipe content to stdout (default: False)
            opts (dict): The keyword arguments passed to the wrapper

        Kwargs:
            conf (dict): The pipe configuration
            extract (str): The key with which to get a value from `conf`. If
                set, the wrapped pipe will receive this value instead of `conf`
                (default: None).

            listize (bool): Ensure that the value returned from an `extract` is
                list-like (default: False)

            pdictize (bool): Convert `conf` or an `extract` to a
                riko.dotdict.DotDict instance (default: True unless
                `listize` is False and `extract` is True)

            objectify (bool): Convert `conf` to a meza.fntools.Objectify
                instance (default: True unless  `ptype` is 'none').

            ptype (str): Used to convert `conf` items to a specific type.
                Performs conversion after obtaining the `objectify` value above.
                If set, objectified `conf` items will be converted upon
                attribute retrieval, and normal `conf` items will be converted
                immediately. Must be one of 'pass', 'none', 'text', or 'num'.
                Default: 'pass', i.e., return `conf` as is. Note: setting to
                'none' automatically disables `objectify`.

            dictize (bool): Convert the input `item` to a DotDict instance
                (default: True)

            field (str): The key with which to get a value from the input
                `item`. If set, the wrapped pipe will receive this value
                instead of `item` (default: None).

            ftype (str): Used to convert the input `item` to a specific type.
                Performs conversion after obtaining the `field` value above.
                If set, the wrapped pipe will receive this value instead of
                `item`. Must be one of 'pass', 'none', 'text', 'int', 'number',
                or 'decimal'. Default: 'pass', i.e., return the item as is.
                Note: setting to 'none' automatically enables `emit`.

            count (str): Stream count. Must be either 'first' (yields only the
                first result) or 'all' (yields all results in a list). Default:
                None (yield all results, but only return a list if there is
                more than one result).

            assign (str): Attribute to assign stream (default: 'content' if
                `ftype` is 'none', pipe name otherwise)

            emit (bool): Return the stream as is and don't assign it to an item
                attribute (default: True if `ftype` is set to 'none', False
                otherwise).

            skip_if (func): A function that takes the `item` and should return
                True if processing should be skipped, or False otherwise. If
                processing is skipped, the resulting stream will be the original
                input `item`.

        Examples:
            >>> from riko.bado import react, util, _issync
            >>> from riko.bado.mock import FakeReactor
            >>>
            >>> @processor()
            ... def pipe(item, objconf, skip=False, **kwargs):
            ...     if skip:
            ...         stream = kwargs['stream']
            ...     else:
            ...         content = item['content']
            ...         stream = 'say "%s" %s times!' % (content, objconf.times)
            ...
            ...     return stream
            ...
            >>> # this is an admittedly contrived example to show how you would
            >>> # call an async function
            >>> @processor(isasync=True)
            ... @coroutine
            ... def async_pipe(item, objconf, skip=False, **kwargs):
            ...     if skip:
            ...         stream = kwargs['stream']
            ...     else:
            ...         content = yield util.async_return(item['content'])
            ...         stream = 'say "%s" %s times!' % (content, objconf.times)
            ...
            ...     return_value(stream)
            ...
            >>> item = {'content': 'hello world'}
            >>> kwargs = {'conf':  {'times': 'three'}, 'assign': 'content'}
            >>> response = {'content': 'say "hello world" three times!'}
            >>> next(pipe(item, **kwargs)) == response
            True
            >>>
            >>> def run(reactor):
            ...     callback = lambda x: print(next(x) == response)
            ...     d = async_pipe(item, **kwargs)
            ...     return d.addCallbacks(callback, logger.error)
            ...
            >>> if _issync:
            ...     True
            ... else:
            ...     try:
            ...         react(run, _reactor=FakeReactor())
            ...     except SystemExit:
            ...         pass
            True
        """
        self.defaults = defaults or {}
        self.opts = opts or {}
        self.async = isasync
        self.debug = debug

    def __call__(self, pipe):
        """Creates a sync/async pipe that processes individual items

        Args:
            pipe (Iter[dict]): The entry to process

        Yields:
            dict: item

        Returns:
            Deferred: twisted.internet.defer.Deferred generator of items

        Examples:
            >>> from riko.bado import react, _issync
            >>> from riko.bado.mock import FakeReactor
            >>>
            >>> kwargs = {
            ...     'ftype': 'text', 'extract': 'times', 'listize': True,
            ...     'pdictize': False, 'emit': True, 'field': 'content',
            ...     'objectify': False}
            ...
            >>> @processor(**kwargs)
            ... def pipe(content, times, skip=False, **kwargs):
            ...     if skip:
            ...         stream = kwargs['stream']
            ...     else:
            ...         value = 'say "%s" %s times!' % (content, times[0])
            ...         stream = {kwargs['assign']: value}
            ...
            ...     return stream
            ...
            >>> # async pipes don't have to return a deferred,
            >>> # they work fine either way
            >>> @processor(isasync=True, **kwargs)
            ... def async_pipe(content, times, skip=False, **kwargs):
            ...     if skip:
            ...         stream = kwargs['stream']
            ...     else:
            ...         value = 'say "%s" %s times!' % (content, times[0])
            ...         stream = {kwargs['assign']: value}
            ...
            ...     return stream
            ...
            >>> item = {'content': 'hello world'}
            >>> kwargs = {'conf':  {'times': 'three'}, 'assign': 'content'}
            >>> response = {'content': 'say "hello world" three times!'}
            >>> next(pipe(item, **kwargs)) == response
            True
            >>>
            >>> def run(reactor):
            ...     callback = lambda x: print(next(x) == response)
            ...     d = async_pipe(item, **kwargs)
            ...     return d.addCallbacks(callback, logger.error)
            ...
            >>> if _issync:
            ...     True
            ... else:
            ...     try:
            ...         react(run, _reactor=FakeReactor())
            ...     except SystemExit:
            ...         pass
            True
        """
        @wraps(pipe)
        def wrapper(item=None, **kwargs):
            module_name = wrapper.__module__.split('.')[-1]

            defaults = {
                'dictize': True, 'ftype': 'pass', 'ptype': 'pass',
                'objectify': True}

            combined = merge([self.defaults, defaults, self.opts, kwargs])
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

            uconf = DotDict(conf) if combined.get('dictize') else conf
            updates = {'conf': uconf, 'assign': combined.get('assign')}
            kwargs.update(updates)

            item = item or {}
            _input = DotDict(item) if combined.get('dictize') else item
            bfuncs = get_broadcast_funcs(**combined)
            skip = get_skip(_input, **combined)
            types = set([]) if skip else {combined['ftype'], combined['ptype']}

            if types.difference({'pass', 'none'}):
                dfuncs = get_dispatch_funcs(**combined)
            else:
                dfuncs = None

            parsed, orig_item = _dispatch(_input, bfuncs, dfuncs=dfuncs)
            kwargs.update({'skip': skip, 'stream': orig_item})

            if self.async:
                stream = yield pipe(*parsed, **kwargs)
            else:
                stream = pipe(*parsed, **kwargs)

            one, assignment = get_assignment(stream, skip=skip, **combined)

            if skip or combined.get('emit'):
                stream = assignment
            elif not skip:
                stream = assign(_input, assignment, one=one, **combined)

            if self.async:
                return_value(stream)
            else:
                for s in stream:
                    yield s

        is_source = self.opts.get('ftype') == 'none'
        wrapper.__dict__['name'] = wrapper.__module__.split('.')[-1]
        wrapper.__dict__['type'] = 'processor'
        wrapper.__dict__['sub_type'] = 'source' if is_source else 'transformer'
        return coroutine(wrapper) if self.async else wrapper


class operator(object):
    def __init__(self, defaults=None, isasync=False, **opts):
        """Creates a sync/async pipe that processes an entire stream of items

        Args:
            defaults (dict): Default `conf` values.
            isasync (bool): Wrap an async pipe (default: False)
            opts (dict): The keyword arguments passed to the wrapper

        Kwargs:
            conf (dict): The pipe configuration
            extract (str): The key with which to get values from `conf`. If set,
                the wrapped pipe will receive these value instead of `conf`
                (default: None).

            listize (bool): Ensure that the value returned from an `extract` is
                list-like (default: False)

            pdictize (bool): Convert `conf` or an `extract` to a
                riko.dotdict.DotDict instance (default: True if either
                `extract` is False or both `listize` and `extract` are True)

            objectify (bool): Convert `conf` to a meza.fntools.Objectify
                instance (default: True unless  `ptype` is 'none').

            ptype (str): Used to convert `conf` items to a specific type.
                Performs conversion after obtaining the `objectify` value above.
                If set, objectified `conf` items will be converted upon
                attribute retrieval, and normal `conf` items will be converted
                immediately. Must be one of 'pass', 'none', 'text', or 'num'.
                Default: 'pass', i.e., return `conf` as is. Note: setting to
                'none' automatically disables `objectify`.

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

            count (str): Stream count. Must be either 'first' (yields only the
                first result) or 'all' (yields all results in a list). Default:
                None (yield all results, but only return a list if there is
                more than one result).

            assign (str): Attribute to assign stream (default: the pipe name)

            emit (bool): return the stream as is and don't assign it to an item
                attribute (default: True).

        Returns:
            func: A function of 1 arg (items) and a `**kwargs`.

        Examples:
            >>> from builtins import sum as _sum, len
            >>> from riko.bado import react, util, _issync
            >>> from riko.bado.mock import FakeReactor
            >>>
            >>> # emit is True by default
            >>> # and operators can't skip items, so the pipe is passed an
            >>> # item dependent version of objconf as the 3rd arg
            >>> @operator(emit=False)
            ... def pipe1(stream, objconf, tuples, **kwargs):
            ...     for item, objconf in tuples:
            ...         s = 'say "%s" %s times!'
            ...         yield s % (item['content'], objconf.times)
            ...
            >>> @operator(emit=False)
            ... def pipe2(stream, objconf, tuples, **kwargs):
            ...     return _sum(len(item['content'].split()) for item in stream)
            ...
            >>> # this is an admittedly contrived example to show how you would
            >>> # call an async function
            >>> @operator(isasync=True, emit=False)
            ... @coroutine
            ... def async_pipe1(stream, objconf, tuples, **kwargs):
            ...     for item, objconf in tuples:
            ...         content = yield util.async_return(item['content'])
            ...         value = 'say "%s" %s times!' % (content, objconf.times)
            ...         return_value(value)
            ...
            >>> # async pipes don't have to return a deferred,
            >>> # they work fine either way
            >>> @operator(isasync=True, emit=False)
            ... def async_pipe2(stream, objconf, tuples, **kwargs):
            ...     return _sum(len(item['content'].split()) for item in stream)
            ...
            >>> items = [{'content': 'hello world'}, {'content': 'bye world'}]
            >>> kwargs = {'conf':  {'times': 'three'}, 'assign': 'content'}
            >>> response = {'content': 'say "hello world" three times!'}
            >>> next(pipe1(items, **kwargs)) == response
            True
            >>> next(pipe2(items, **kwargs)) == {'content': 4}
            True
            >>>
            >>> @coroutine
            ... def run(reactor):
            ...     r1 = yield async_pipe1(items, **kwargs)
            ...     print(next(r1) == response)
            ...     r2 = yield async_pipe2(items, **kwargs)
            ...     print(next(r2) == {'content': 4})
            ...
            >>> if _issync:
            ...     True
            ...     True
            ... else:
            ...     try:
            ...         react(run, _reactor=FakeReactor())
            ...     except SystemExit:
            ...         pass
            True
            True
        """
        self.defaults = defaults or {}
        self.opts = opts or {}
        self.async = isasync

    def __call__(self, pipe):
        """Creates a wrapper that allows a sync/async pipe to processes a
        stream of items

        Args:
            pipe (func): A function of 4 args (stream, objconf, tuples)
                and a `**kwargs`. TODO: document args & kwargs.

        Returns:
            func: A function of 1 arg (items) and a `**kwargs`.

        Examples:
            >>> from builtins import sum as _sum, len
            >>> from riko.bado import react, _issync
            >>> from riko.bado.mock import FakeReactor
            >>> from riko.bado.util import maybeDeferred
            >>>
            >>> opts = {
            ...     'ftype': 'text', 'extract': 'times', 'listize': True,
            ...     'pdictize': False, 'emit': True, 'field': 'content',
            ...     'objectify': False}
            ...
            >>> wrapper = operator(**opts)
            >>>
            >>> def pipe1(stream, objconf, tuples, **kwargs):
            ...     for content, times in tuples:
            ...         value = 'say "%s" %s times!' % (content, times[0])
            ...         yield {kwargs['assign']: value}
            ...
            >>> def pipe2(stream, objconf, tuples, **kwargs):
            ...     word_cnt = _sum(len(content.split()) for content in stream)
            ...     return {kwargs['assign']: word_cnt}
            ...
            >>> wrapped_pipe1 = wrapper(pipe1)
            >>> wrapped_pipe2 = wrapper(pipe2)
            >>> items = [{'content': 'hello world'}, {'content': 'bye world'}]
            >>> kwargs = {'conf':  {'times': 'three'}, 'assign': 'content'}
            >>> response = {'content': 'say "hello world" three times!'}
            >>>
            >>> next(wrapped_pipe1(items, **kwargs)) == response
            True
            >>> next(wrapped_pipe2(items, **kwargs)) == {'content': 4}
            True
            >>> async_wrapper = operator(isasync=True, **opts)
            >>>
            >>> # async pipes don't have to return a deferred,
            >>> # they work fine either way
            >>> def async_pipe1(stream, objconf, tuples, **kwargs):
            ...     for content, times in tuples:
            ...         value = 'say "%s" %s times!' % (content, times[0])
            ...         yield {kwargs['assign']: value}
            ...
            >>> # this is an admittedly contrived example to show how you would
            >>> # call an async function
            >>> @coroutine
            ... def async_pipe2(stream, objconf, tuples, **kwargs):
            ...     words = (len(content.split()) for content in stream)
            ...     word_cnt = yield maybeDeferred(_sum, words)
            ...     return_value({kwargs['assign']: word_cnt})
            ...
            >>> wrapped_async_pipe1 = async_wrapper(async_pipe1)
            >>> wrapped_async_pipe2 = async_wrapper(async_pipe2)
            >>>
            >>> @coroutine
            ... def run(reactor):
            ...     r1 = yield wrapped_async_pipe1(items, **kwargs)
            ...     print(next(r1) == response)
            ...     r2 = yield wrapped_async_pipe2(items, **kwargs)
            ...     print(next(r2) == {'content': 4})
            ...
            >>> if _issync:
            ...     True
            ...     True
            ... else:
            ...     try:
            ...         react(run, _reactor=FakeReactor())
            ...     except SystemExit:
            ...         pass
            True
            True
        """
        @wraps(pipe)
        def wrapper(items=None, **kwargs):
            module_name = wrapper.__module__.split('.')[-1]
            wrapper.__dict__['name'] = module_name

            defaults = {
                'dictize': True, 'ftype': 'pass', 'ptype': 'pass',
                'objectify': True, 'emit': True, 'assign': module_name}

            combined = merge([self.defaults, defaults, self.opts, kwargs])
            extracted = 'extract' in combined
            pdictize = combined.get('listize') if extracted else True

            combined.setdefault('pdictize', pdictize)
            conf = {k: combined[k] for k in self.defaults}
            conf.update(kwargs.get('conf', {}))
            combined.update({'conf': conf})

            uconf = DotDict(conf) if combined.get('dictize') else conf
            updates = {'conf': uconf, 'assign': combined.get('assign')}
            kwargs.update(updates)

            items = items or iter([])
            _INPUT = map(DotDict, items) if combined.get('dictize') else items
            bfuncs = get_broadcast_funcs(**combined)
            types = {combined['ftype'], combined['ptype']}

            if types.difference({'pass', 'none'}):
                dfuncs = get_dispatch_funcs(**combined)
            else:
                dfuncs = None

            pairs = (_dispatch(item, bfuncs, dfuncs=dfuncs) for item in _INPUT)
            parsed, _ = _dispatch(DotDict(), bfuncs, dfuncs=dfuncs)

            # - operators can't skip items
            # - purposely setting both variables to maps of the same iterable
            #   since only one is intended to be used at any given time
            # - `tuples` is an iterator of tuples of the first two `parsed`
            #   elements
            tuples = ((p[0][0], p[0][1]) for p in pairs)
            orig_stream = (p[0][0] for p in pairs)
            objconf = parsed[1]

            if self.async:
                stream = yield pipe(orig_stream, objconf, tuples, **kwargs)
            else:
                stream = pipe(orig_stream, objconf, tuples, **kwargs)

            sub_type = 'aggregator' if hasattr(stream, 'keys') else 'composer'
            wrapper.__dict__['sub_type'] = sub_type

            # operators can only assign one value per item and can't skip items
            _, assignment = get_assignment(stream, **combined)

            if combined.get('emit'):
                stream = assignment
            else:
                singles = (iter([v]) for v in assignment)
                assigned = (
                    assign({}, s, one=True, **combined) for s in singles)

                stream = multiplex(assigned)

            if self.async:
                return_value(stream)
            else:
                for s in stream:
                    yield s

        wrapper.__dict__['type'] = 'operator'
        return coroutine(wrapper) if self.async else wrapper


def _dispatch(item, bfuncs, dfuncs=None):
    split = broadcast(item, *bfuncs)
    parsed = dispatch(split, *dfuncs) if dfuncs else split
    return parsed, item


def get_broadcast_funcs(**kwargs):
    kw = Objectify(kwargs, conf={})
    pieces = kw.conf[kw.extract] if kw.extract else kw.conf
    no_conf = remove_keys(kwargs, 'conf')
    noop = partial(cast, _type='none')

    if kw.listize:
        listed = listize(pieces)
        piece_defs = map(DotDict, listed) if kw.pdictize else listed
        parser = partial(parse_conf, **no_conf)
        pfuncs = [partial(parser, conf=conf) for conf in piece_defs]
        get_pieces = lambda item: broadcast(item, *pfuncs)
    elif kw.ptype != 'none':
        conf = DotDict(pieces) if kw.pdictize and pieces else pieces
        get_pieces = partial(parse_conf, conf=conf, **no_conf)
    else:
        get_pieces = noop

    ffunc = noop if kw.ftype == 'none' else partial(get_field, **kwargs)
    return (ffunc, get_pieces)


def get_dispatch_funcs(**kwargs):
    pfunc = partial(cast, _type=kwargs['ptype'])
    field_dispatch = partial(cast, _type=kwargs['ftype'])

    if kwargs['objectify'] and kwargs['ptype'] not in {'none', 'pass'}:
        piece_dispatch = lambda p: Objectify(p.items(), func=pfunc)
    else:
        piece_dispatch = pfunc

    return [field_dispatch, piece_dispatch]
