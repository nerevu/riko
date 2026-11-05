# vim: sw=4:ts=4:expandtab
r"""
Replaces text in item fields using regular expressions.

Search-and-replace on steroids. Each rule reads "in *field*, replace *match*
with *replace*", and several rules can run in sequence. Unlike most modules, this
rewrites fields on the item itself rather than producing a separate value, so
rules may target different fields in one pass.

Examples:

    Basic usage::

        >>> from riko.modules.regex import pipe
        >>>
        >>> match = r"(\w+)\s(\w+)"
        >>> rule = {"field": "content", "match": match, "replace": "$2wide"}
        >>> item = {"content": "hello world"}
        >>> next(pipe(item, conf={"rule": rule}))["content"]
        'worldwide'

Attributes:

    OPTS: Processor decoration options.
    DEFAULTS: Default processor configuration.

"""

from __future__ import annotations

from functools import partial, reduce
from operator import itemgetter
from typing import TYPE_CHECKING, Any, cast

from riko.bado.itertools import async_reduce, coop_reduce
from riko.base._funcutils import resolve_default
from riko.base._logging import get_logger
from riko.base._sentinels import MISSING
from riko.coercion._dataclass import build_regex_rule
from riko.parsing._dotdict import DotDict

from ._decorators import processor
from ._sortutils import group_by
from ._textops import Substitution, gen_rule_passes, substitute_pass

if TYPE_CHECKING:
    from collections.abc import Sequence
    from logging import Logger

    from riko.coercion._configs import RegexObjconf
    from riko.types._options import DecorationOptions, Defaults
    from riko.types._streams import Item
    from riko.types._values import RikoValue
    from riko.types.modules import RegexConfRule, RegexRule

logger: Logger = get_logger(__name__)

OPTS: DecorationOptions = {"listize": True, "extract": "rule", "emit": True}
DEFAULTS: Defaults = {}


def _resolve_text(result: Substitution, default: str | None) -> str:
    """Resolves a field's rewritten text, falling back when no rule matched."""
    return result.text if result.replacements or default is None else default


async def async_parser(
    item: Item, rules: Sequence[RegexConfRule], objconf: RegexObjconf, **kwargs: object
) -> Item:
    """
    Asynchronously applies each rule to the field it names.

    Rules are grouped by field, so one pass can rewrite several fields.

    Args:

        item: The entry to process.
        rules: The parsed replacement rules.
        objconf: The module configuration.

    Returns:

        The item with each named field rewritten.

    Examples:

        >>> from riko import run
        >>> from meza.fntools import Objectify
        >>>
        >>> item = DotDict({"content": "hello world", "title": "greeting"})
        >>> match = r"(\\w+)\\s(\\w+)"
        >>> replace = "$2wide"
        >>>
        >>> async def main():
        ...     rule = {"field": "content", "match": match, "replace": replace}
        ...     conf = {"rule": rule}
        ...     objconf = Objectify(conf)
        ...     rules = [Objectify(rule)]
        ...     kwargs = {"stream": item, "conf": conf}
        ...     result = await async_parser(item, rules, objconf, **kwargs)
        ...     print(result["content"])
        >>>
        >>> run(main)
        worldwide

    """
    defaults = resolve_default(objconf.default)

    async def areducer(item: Item, rules: Sequence[RegexRule]) -> DotDict[RikoValue]:
        field = rules[0]["field"]
        word = item.get(field, MISSING, **kwargs)

        if word is MISSING or word is None:
            replacement = word
        else:
            passes = list(gen_rule_passes(rules))
            initial = Substitution(str(word))
            result = await coop_reduce(substitute_pass, passes, initial)
            replacement = _resolve_text(result, defaults.get(field))

        rewritten = {} if replacement is MISSING else {field: replacement}
        result = DotDict({**item, **rewritten})
        return cast("DotDict[RikoValue]", result)

    regex_rules = map(partial(build_regex_rule, recompile=True), rules)
    grouped = group_by(regex_rules, "field", ignore_case=True)
    field_rules = map(itemgetter(1), grouped)
    return await async_reduce(areducer, field_rules, item)


def parser(
    item: Item, rules: Sequence[RegexConfRule], objconf: RegexObjconf, **kwargs: object
) -> Item:
    """
    Applies each rule to the field it names.

    Rules are grouped by field, so one pass can rewrite several fields.

    Args:

        item: The entry to process.
        rules: The parsed replacement rules.
        objconf: The module configuration.

    Returns:

        The item with each named field rewritten.

    Examples:

        >>> from meza.fntools import Objectify
        >>>
        >>> item = DotDict({"content": "hello world", "title": "greeting"})
        >>> match = r"(\\w+)\\s(\\w+)"
        >>> rule = {"field": "content", "match": match, "replace": "$2wide"}
        >>> conf = {"rule": rule}
        >>> objconf = Objectify(conf)
        >>> rules = [Objectify(rule)]
        >>> kwargs = {"stream": item, "conf": conf}
        >>> parser(item, rules, objconf, **kwargs)
        {'content': 'worldwide', 'title': 'greeting'}

    """
    defaults = resolve_default(objconf.default)

    def reducer(item: Item, rules: Sequence[RegexRule]) -> DotDict[RikoValue]:
        field = str(rules[0]["field"])
        word = item.get(field, MISSING, **kwargs)

        if word is MISSING or word is None:
            replacement = word
        else:
            initial = Substitution(str(word))
            result = reduce(substitute_pass, gen_rule_passes(rules), initial)
            replacement = _resolve_text(result, defaults.get(field))

        rewritten = {} if replacement is MISSING else {field: replacement}
        result = DotDict({**item, **rewritten})
        return cast("DotDict[RikoValue]", result)

    regex_rules = [build_regex_rule(r, recompile=True) for r in rules]
    grouped = group_by(regex_rules, "field", ignore_case=True)
    field_rules = map(itemgetter(1), grouped)
    return reduce(reducer, field_rules, item)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Item:
    """
    Asynchronously replaces text in item fields using regexes.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:

        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The module configuration.

            rule (dict | list[dict]): The replacement criteria. Required.

                field (str): Item field to rewrite.

                match (str): Regex to search for.

                replace (str): Replacement text. ``$1``, ``$2``, ... refer to
                    capture groups.

                casematch (bool): Whether to match case sensitively
                    (default: False).

                singlelinematch (bool): Whether to replace only the first match
                    and confine ``^``, ``$`` and ``.`` to one line
                    (default: False).

                seriesmatch (bool): Whether this rule rewrites the previous
                    rule's output. Consecutive rules with ``seriesmatch`` False
                    all match the original text in one pass, leftmost match
                    first (default: True).

            default (dict): Value per field to use when none of the field's
                rules matches (default: {}, i.e. keep the original).

        context (Context): the run environment

    Kwargs:

        assign (str): Field the rewritten item is nested under. Ignored when
            ``emit`` is True (default: "regex").

        emit (bool): Whether to emit the rewritten item directly rather than
            nest it. Overrides ``assign`` (default: True).

    Yields:

        - the rewritten ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Raises:

        TypeError: If ``conf`` has no ``rule`` key.
        re.error: If a rule's ``replace`` refers to a group its ``match`` lacks.

    Notes:

        A rule naming a field the item lacks is skipped, leaving the item
        untouched.

    Examples:

        >>> from riko import run
        >>>
        >>> item = {"content": "hello world", "title": "greeting"}
        >>> match = r"(\\w+)\\s(\\w+)"
        >>>
        >>> async def main():
        ...     rule = {"field": "content", "match": match, "replace": "$2wide"}
        ...     conf = {"rule": rule}
        ...     result = async_pipe(item, conf=conf)
        ...     print((await anext(result))["content"])
        >>>
        >>> run(main)
        worldwide

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Item:
    """
    Replaces text in item fields using regexes.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:

        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The module configuration.

            rule (dict | list[dict]): The replacement criteria. Required.

                field (str): Item field to rewrite.

                match (str): Regex to search for.

                replace (str): Replacement text. ``$1``, ``$2``, ... refer to
                    capture groups.

                casematch (bool): Whether to match case sensitively
                    (default: False).

                singlelinematch (bool): Whether to replace only the first match
                    and confine ``^``, ``$`` and ``.`` to one line
                    (default: False).

                seriesmatch (bool): Whether this rule rewrites the previous
                    rule's output. Consecutive rules with ``seriesmatch`` False
                    all match the original text in one pass, leftmost match
                    first (default: True).

            default (dict): Value per field to use when none of the field's
                rules matches (default: {}, i.e. keep the original).

        context (Context): the run environment

    Kwargs:

        assign (str): Field the rewritten item is nested under. Ignored when
            ``emit`` is True (default: "regex").

        emit (bool): Whether to emit the rewritten item directly rather than
            nest it. Overrides ``assign`` (default: True).

    Yields:

        - the rewritten ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Raises:

        TypeError: If ``conf`` has no ``rule`` key.
        re.error: If a rule's ``replace`` refers to a group its ``match`` lacks.

    Notes:

        A rule naming a field the item lacks is skipped, leaving the item
        untouched.

    Examples:

        >>> item = {"content": "hello world", "title": "greeting"}
        >>> match = r"(\\w+)\\s(\\w+)"
        >>> rule = {"field": "content", "match": match, "replace": "$2wide"}
        >>> next(pipe(item, conf={"rule": rule}))
        {'content': 'worldwide', 'title': 'greeting'}

    """
    return parser(*args, **kwargs)
