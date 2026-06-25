# vim: sw=4:ts=4:expandtab
"""
Provides functions for modifying the content of a field of an item using
regular expressions, a powerful type of pattern matching.

Think of it as search-and-replace on steriods. You can define multiple Regex
rules. Each has the general format: "In [field] replace [regex pattern] with
[text]".

Examples:
    basic usage::

        >>> from riko.modules.regex import pipe
        >>>
        >>> match = r'(\\w+)\\s(\\w+)'
        >>> rule = {'field': 'content', 'match': match, 'replace': '$2wide'}
        >>> conf = {'rule': rule}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))['content']
        'worldwide'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections.abc import Mapping, Sequence
from functools import reduce
from typing import cast

import pygogo as gogo

from riko import Objconf
from riko.bado.itertools import async_reduce, coop_reduce
from riko.dotdict import DotDict
from riko.types.general import Defaults, Item, Opts
from riko.types.modules import RegexConfRule, RegexRule
from riko.utils import get_regex_rule, group_by, multi_substitute, substitute

from . import processor

OPTS: Opts = {"listize": True, "extract": "rule", "emit": True}
DEFAULTS: Defaults = {"convert": True, "multi": False}
logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    item: Item,
    rules: Sequence[RegexConfRule],
    objconf: Objconf,
    **kwargs,
) -> DotDict | str | None:
    """
    Asynchronously parsers the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        rules (List[obj]): the parsed rules (Objectify instances).
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        Deferred: twisted.internet.defer.Deferred dict

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from meza.fntools import Objectify
        >>>
        >>> item = DotDict({'content': 'hello world', 'title': 'greeting'})
        >>> match = r'(\\w+)\\s(\\w+)'
        >>> replace = '$2wide'
        >>>
        >>> async def run(reactor):
        ...     rule = {'field': 'content', 'match': match, 'replace': replace}
        ...     conf = {'rule': rule, 'multi': False, 'convert': True}
        ...     objconf = Objectify(conf)
        ...     rules = [Objectify(rule)]
        ...     kwargs = {'stream': item, 'conf': conf}
        ...     result = await async_parser(item, rules, objconf, **kwargs)
        ...     print(result['content'])
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        worldwide

    """
    multi = objconf.multi
    recompile = not multi

    async def async_reducer(
        item: Item, rules: Sequence[RegexRule]
    ) -> DotDict | str | None:
        field = rules[0]["field"]

        if isinstance(item, Mapping):
            word = str(item.get(field, **kwargs))
        elif isinstance(item, str):
            word = item
        else:
            msg = f"{item=} is a {type(item)=}, not a mapping or string, skipping"
            logger.warning(msg)
            word = None

        if word is None:
            replacement = None
        else:
            grouped = group_by(rules, "flags")
            group_rules = [g[1] for g in grouped] if multi else rules
            reducer = multi_substitute if multi else substitute
            replacement = await coop_reduce(reducer, group_rules, word)

        if isinstance(item, Mapping):
            result = DotDict(cast(dict, {**item, field: replacement}))
        else:
            result = replacement

        return result

    regex_rules = [get_regex_rule(r, recompile=recompile) for r in rules]
    grouped = group_by(regex_rules, "field")
    field_rules = [g[1] for g in grouped]
    item = await async_reduce(async_reducer, field_rules, item)
    return cast(DotDict | str | None, item)


def parser(
    item: Item,
    rules: Sequence[RegexConfRule],
    objconf: Objconf,
    **kwargs,
) -> DotDict | str | None:
    """
    Parsers the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        rules (List[obj]): the parsed rules (Objectify instances).
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = DotDict({'content': 'hello world', 'title': 'greeting'})
        >>> match = r'(\\w+)\\s(\\w+)'
        >>> rule = {'field': 'content', 'match': match, 'replace': '$2wide'}
        >>> conf = {'rule': rule, 'multi': False, 'convert': True}
        >>> objconf = Objectify(conf)
        >>> rules = [Objectify(rule)]
        >>> kwargs = {'stream': item, 'conf': conf}
        >>> regexed = parser(item, rules, objconf, **kwargs)
        >>> regexed
        {'content': 'worldwide', 'title': 'greeting'}
        >>> conf['multi'] = True
        >>> parser(item, rules, objconf, **kwargs)
        {'content': 'worldwide', 'title': 'greeting'}

    """
    multi = objconf.multi
    recompile = not multi

    def sync_reducer(item: Item, rules: Sequence[RegexRule]) -> DotDict | str | None:
        field = str(rules[0]["field"])

        if isinstance(item, Mapping):
            word = str(item.get(field, **kwargs))
        elif isinstance(item, str):
            msg = f"{item=} is a {type(item)=}, not a mapping, ignoring {field=} and"
            msg += "applying regexes to the string itself."
            logger.warning(msg)
            word = item
        else:
            msg = f"{item=} is a {type(item)=}, not a mapping or string, skipping"
            logger.warning(msg)
            word = None

        if word is None:
            replacement = None
        else:
            grouped = group_by(rules, "flags")
            group_rules = [g[1] for g in grouped] if multi else rules
            reducer = multi_substitute if multi else substitute
            replacement = reduce(reducer, group_rules, word)

        if isinstance(item, Mapping):
            result = DotDict(cast(dict, {**item, field: replacement}))
        else:
            result = replacement

        return result

    regex_rules = [get_regex_rule(r, recompile=recompile) for r in rules]
    grouped = group_by(regex_rules, "field")
    field_rules = [g[1] for g in grouped]
    item = reduce(sync_reducer, field_rules, item)
    return cast(DotDict | str | None, item)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args, **kwargs) -> DotDict | str | None:
    """
    A processor that asynchronously replaces text in fields of an item
    using regexes.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'. May
            contain the keys 'multi' or 'convert'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the keys 'field', 'match', and 'replace'.

                field (str): The item attribute to search
                match (str): The regex to apply
                replace (str): The string replacement
                default (str): Default if search pattern isn't found (
                    default: None, i.e, return the original string)

                singlematch (bool): Stop after first match (default: False)
                singlelinematch (bool): Don't search across newlines with '^',
                    '$', or '.' (default: False)

                casematch (bool): Perform case sensitive match (default: False)

            multi (bool): Efficiently combine multiple regexes (default: False)
            convert (bool): Convert regex into a Python compatible format
                (default: True)

    Yields:
        Deferred: twisted.internet.defer.Deferred item with replaced content

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> item = {'content': 'hello world', 'title': 'greeting'}
        >>> match = r'(\\w+)\\s(\\w+)'
        >>> replace = '$2wide'
        >>>
        >>> async def run(reactor):
        ...     rule = {'field': 'content', 'match': match, 'replace': replace}
        ...     conf = {'rule': rule, 'multi': False, 'convert': True}
        ...     result = await async_pipe(item, conf=conf)
        ...     print(next(result)['content'])
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        worldwide

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> DotDict | str | None:
    """
    A processor that replaces text in fields of an item using regexes.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'. May
            contain the keys 'multi' or 'convert'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the keys 'field', 'match', and 'replace'.

                field (str): The item attribute to search
                match (str): The regex to apply
                replace (str): The string replacement
                default (str): Default if search pattern isn't found (
                    default: None, i.e, return the original string)

                seriesmatch (bool): Search with rule in series (not parallel with other
                    rules) (default: True)
                singlematch (bool): Stop after first match (default: False)
                singlelinematch (bool): Don't search across newlines with '^',
                    '$', or '.' (default: False)

                casematch (bool): Perform case sensitive match (default: False)

            multi (bool): Efficiently combine multiple regexes (default: False)
            convert (bool): Convert regex into a Python compatible format
                (default: True)

    Yields:
        dict: an item with replaced content

    Examples:
        >>> # default matching
        >>> item = {'content': 'hello world', 'title': 'greeting'}
        >>> match = r'(\\w+)\\s(\\w+)'
        >>> rule = {'field': 'content', 'match': match, 'replace': '$2wide'}
        >>> conf = {'rule': rule, 'multi': False, 'convert': True}
        >>> result = next(pipe(item, conf=conf))
        >>> result
        {'content': 'worldwide', 'title': 'greeting'}
        >>> # multiple regex mode
        >>> conf['multi'] = True
        >>> next(pipe(item, conf=conf))
        {'content': 'worldwide', 'title': 'greeting'}
        >>> # case insensitive matching
        >>> item = {'content': 'Hello hello'}
        >>> rule.update({'match': r'hello.*', 'replace': 'bye'})
        >>> next(pipe(item, conf=conf))['content']
        'bye'
        >>> # case sensitive matching
        >>> rule['casematch'] = True
        >>> next(pipe(item, conf=conf))['content']
        'Hello bye'

    """
    return parser(*args, **kwargs)
