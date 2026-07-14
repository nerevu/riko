# vim: sw=4:ts=4:expandtab
"""
Provides utility classes and functions
"""

import builtins
import datetime
import fcntl
import itertools as it
import re
import sys
from codecs import StreamReader
from collections import deque
from collections.abc import (
    Callable,
    Generator,
    ItemsView,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from dataclasses import asdict, fields, is_dataclass
from decimal import Decimal
from functools import cache, partial, reduce, wraps
from http.client import HTTPResponse
from io import BytesIO, RawIOBase, StringIO, TextIOBase
from math import isnan
from operator import itemgetter
from os import O_NONBLOCK
from time import struct_time
from typing import (
    TYPE_CHECKING,
    Literal,
    Protocol,
    TypeGuard,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    overload,
)
from typing import cast as cast_type
from urllib.error import URLError
from urllib.request import Request, urlopen
from urllib.response import addinfourl

import mezmorize
import pygogo as gogo
import requests
from meza.io import reencode
from mezmorize.utils import get_cache_type
from requests.structures import CaseInsensitiveDict

import riko.cast as cast_module
from riko import (
    ENCODING,
    Context,
    Objconf,
    Objectify,
    __version__,
    get_abspath,
    listize,
    replacer,
)
from riko.cast import CAST_SWITCH, CastType
from riko.cast import cast as cast_value
from riko.dates import ensure_tzinfo
from riko.dotdict import DotDict
from riko.types.compile import ParsedPipeDef, PipeDef, PipeModule, Wire
from riko.types.general import (
    FileTypes,
    Item,
    Opener,
    PipelineDependencies,
    Stream,
    StreamOrValueStream,
    ValueStream,
)
from riko.types.modules import (
    EmbeddedModule,
    InputRawConf,
    LoopRawConf,
    RegexConfRule,
    RegexRule,
)
from riko.types.values import (
    BasicArg,
    BasicDict,
    BasicValue,
    Hashable,
    HashableType,
    ParserRSSEntry,
    PrimitiveValue,
    RikoDict,
    RikoList,
    RikoValue,
    RSSEntry,
    SortableValue,
    StatefulItem,
    StreamState,
    StringyDict,
    StringyList,
)

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

NON_SORTABLE = (Mapping, Sequence)

_registry: dict[str, Generator[None, Item | StatefulItem, None]] = {}
_receive_queue: dict[str, deque[tuple[StreamState | None, Item]]] = {}

logger = gogo.Gogo(__name__, verbose=False, monolog=True).logger
noop = lambda item: item

T_co = TypeVar("T_co", covariant=True)
B = TypeVar("B", Literal[True], Literal[False])
VT = TypeVar("VT")

type TuplePair = tuple[str, HashableOrTuple]
type InnerPairs = tuple[TuplePair, ...]
type DataclassTuple = tuple[str, tuple[type, InnerPairs]]
type CollectionTuple = tuple[type, InnerPairs | tuple[HashableOrTuple, ...]]
type HashableOrTuple = Hashable | CollectionTuple | DataclassTuple


def is_dataclass_tuple(obj: tuple) -> TypeGuard[DataclassTuple]:
    return obj[0] == "dataclass"


class ReprCacheWrapper(Protocol[T_co]):
    def __call__(  # noqa: E704
        self, *args: VT, **kwargs: VT
    ) -> T_co: ...
    def cache_clear(self) -> None: ...  # noqa: E704
    def cache_info(self) -> object: ...  # noqa: E704


def fromdict(
    cls: type["DataclassInstance"],
    **data: Union["DataclassInstance", RikoValue, StringyList, StringyDict],
) -> "DataclassInstance":
    module = sys.modules[cls.__module__]
    localns = {**vars(module), **vars(cast_module)}
    hints = get_type_hints(cls, localns=localns, include_extras=True)

    for f in fields(cls):
        if f.name not in data:
            continue

        ftype = hints[f.name]
        val = data[f.name]
        origin = get_origin(ftype)

        if origin is Union:
            args = [a for a in get_args(ftype) if a is not type(None)]
            ftype = args[0] if args else ftype
            origin = get_origin(ftype)

        if origin is Literal:
            valid = get_args(ftype)

            if val not in valid:
                raise ValueError(f"Invalid {f.name}={val!r}, expected one of {valid}")
        elif is_dataclass(ftype) and isinstance(ftype, type) and isinstance(val, dict):
            val = fromdict(ftype, **val)

        data[f.name] = val

    return cls(**data)


def _to_hashable(obj: object) -> HashableOrTuple:
    hashed = None

    if obj is None:
        pass
    elif isinstance(obj, HashableType):
        hashed = obj
    elif isinstance(obj, DotDict):
        inner = sorted((k, _to_hashable(v)) for k, v in obj._store.values())
        hashed = (DotDict, tuple(inner))
    elif isinstance(obj, Mapping):
        inner = sorted((k, _to_hashable(v)) for k, v in obj.items())
        typ = Objectify if isinstance(obj, Objectify) else dict
        hashed = (typ, tuple(inner))
    elif isinstance(obj, Sequence):
        hashed = (list, tuple(_to_hashable(v) for v in obj))
    elif is_dataclass(obj):
        items = asdict(cast("DataclassInstance", obj)).items()
        inner = tuple(sorted((k, _to_hashable(v)) for k, v in items))
        hashed = ("dataclass", (type(obj), inner))
    else:
        logger.error(f"Unsupported {type(obj)=}")

    return hashed


@cache
def _from_hashable(
    obj: HashableOrTuple,
) -> Union[RikoValue, Objectify, "DataclassInstance", CollectionTuple, DataclassTuple]:
    if not isinstance(obj, struct_time) and isinstance(obj, tuple) and len(obj) == 2:
        if is_dataclass_tuple(obj):
            typ, (cls, inner) = obj
        else:
            typ, inner = cast(CollectionTuple, obj)
            cls = None

        if typ in (Objectify, DotDict, dict, "dataclass"):
            _arg = {k: _from_hashable(v) for k, v in cast(InnerPairs, inner)}
            arg = cast(RikoDict, _arg)

            if (typ is Objectify) or (typ is DotDict):
                arg = typ(arg)
            elif cls and typ == "dataclass":
                arg = fromdict(cls, **arg)
        elif typ is list:
            _arg = [_from_hashable(v) for v in cast(tuple[HashableOrTuple, ...], inner)]
            arg = cast(RikoList, _arg)
        else:
            arg = obj
    else:
        arg = obj

    return arg


def repr_cache[R](fn: Callable[..., R]) -> ReprCacheWrapper[R]:
    @cache
    def _cached(hashable_args: tuple, hashable_kwargs: tuple) -> R:
        args = tuple(_from_hashable(a) for a in hashable_args)
        kwargs = {k: _from_hashable(v) for k, v in hashable_kwargs}
        return fn(*args, **kwargs)

    @wraps(fn)
    def wrapper(*args: VT, **kwargs: VT) -> R:
        return _cached(
            tuple(_to_hashable(a) for a in args),
            tuple(sorted((k, _to_hashable(v)) for k, v in kwargs.items())),
        )

    setattr(wrapper, "cache_clear", _cached.cache_clear)  # noqa: B010
    setattr(wrapper, "cache_info", _cached.cache_info)  # noqa: B010
    return cast(ReprCacheWrapper[R], wrapper)


# https://trac.edgewall.org/ticket/2066#comment:1
# http://stackoverflow.com/a/22675049/408556
def make_blocking(f):
    fd = f.fileno()
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)

    if flags & O_NONBLOCK:
        blocking = flags & ~O_NONBLOCK
        fcntl.fcntl(fd, fcntl.F_SETFL, blocking)


def default_user_agent(name="riko"):
    """
    Return a string representing the default user agent.
    :rtype: str
    """
    return f"{name}/{__version__}"


class Chainable:
    def __init__(self, data, method=None):
        self.data = data
        self.method = method
        self.list = list(data)

    def __getattr__(self, name):
        funcs = (partial(getattr, x) for x in [self.data, builtins, it])
        zipped = zip(funcs, it.repeat(AttributeError))
        method = multi_try(name, zipped, default=None)
        return Chainable(self.data, method)

    def __call__(self, *args, **kwargs):
        try:
            return Chainable(self.method(self.data, *args, **kwargs))
        except TypeError:
            return Chainable(self.method(args[0], self.data, **kwargs))


def invert_dict(d):
    return {v: k for k, v in d.items()}


def multi_try(source, zipped, default=None):
    for func, error in zipped:
        try:
            value = func(source)
        except error:
            pass
        else:
            break
    else:
        value = default

    return value


def get_response_content_type(r: HTTPResponse | addinfourl | requests.Response) -> str:
    content_type = r.headers.get("Content-Type", "")
    return content_type.lower()


def get_response_encoding(r: HTTPResponse | addinfourl, def_encoding=ENCODING) -> str:
    content_type = get_response_content_type(r)

    if "charset=" in content_type:
        ctype = content_type.split("charset=")[1]
        encoding = ctype.strip().strip('"').strip("'")
    else:
        encoding = None

    return encoding or def_encoding


# https://docs.python.org/3.3/reference/expressions.html#examples
def auto_close[T](stream: Iterable[T], f: FileTypes) -> Iterator[T]:
    try:
        yield from stream
    finally:
        f.close()


@overload
def opener(  # noqa: E704
    url: str,
    memoize: Literal[True],
    delay: int = ...,
    encoding: str = ...,
    params: dict | None = ...,
    offline: bool = ...,
    *,
    binary: Literal[True],
    **kwargs,
) -> tuple[BytesIO, str | None]: ...


@overload
def opener(  # noqa: E704
    url: str,
    memoize: Literal[False] = ...,
    delay: int = ...,
    encoding: str = ...,
    params: dict | None = ...,
    offline: bool = ...,
    *,
    binary: Literal[True],
    **kwargs,
) -> tuple[RawIOBase, str | None]: ...


@overload
def opener(  # noqa: E704
    url: str,
    memoize: Literal[True],
    delay: int = ...,
    encoding: str = ...,
    params: dict | None = ...,
    offline: bool = ...,
    binary: Literal[False] = ...,
    **kwargs,
) -> tuple[StringIO, str | None]: ...


@overload
def opener(  # noqa: E704
    url: str,
    memoize: Literal[False] = ...,
    delay: int = ...,
    encoding: str = ...,
    params: dict | None = ...,
    offline: bool = ...,
    binary: Literal[False] = ...,
    **kwargs,
) -> tuple[StreamReader, str | None]: ...


def opener(  # noqa: E302
    url: str,
    memoize=False,
    delay=0,
    encoding=ENCODING,
    params=None,
    offline=True,
    binary: bool = False,
    **kwargs,
) -> tuple[FileTypes, str | None]:
    params = params or {}
    timeout = kwargs.get("timeout")
    url = get_abspath(url, offline=offline)
    r = None

    if url.startswith("http") and params:
        r = requests.get(url, params=params, stream=binary, timeout=timeout)
        r.raw.decode_content = not binary

        if binary:
            response = BytesIO(r.content) if memoize else cast(RawIOBase, r.raw)
        elif memoize:
            response = StringIO(r.text)
        else:
            encoding = r.encoding or encoding
            reencoded = reencode(r.raw, encoding, decode=True)
            # TODO: Add self._f = f to Reencoder
            reencoded._r = r  # pyright: ignore[reportAttributeAccessIssue]
            response = cast(StreamReader, reencoded)
    else:
        req = Request(url, headers={"User-Agent": default_user_agent()})  # noqa: S310

        if delay:
            logger.debug("Request delaying not currently implemented.")

        if (r := urlopen(req, timeout=timeout)) and binary:  # noqa: S310
            response = BytesIO(r.read()) if memoize else cast(RawIOBase, r)
        elif r:
            encoding = get_response_encoding(r, encoding)

            if not (binary or encoding):
                encoding = ENCODING

            if memoize and encoding:
                response = StringIO(r.read().decode(encoding))
            elif memoize:
                response = StringIO(r.read())
            elif encoding:
                reencoded = reencode(r.fp, encoding, decode=True)
                # TODO: Add self._f = f to Reencoder
                reencoded._r = r  # pyright: ignore[reportAttributeAccessIssue]
                response = cast(StreamReader, reencoded)
            else:
                response = cast(TextIOBase, r)
        else:
            response = BytesIO() if binary else StringIO()

    content_type = get_response_content_type(r) if r else None
    return (response, content_type)


@repr_cache
def get_opener(memoize=False, **kwargs) -> Opener:
    """
    Examples:
        >>> get_opener.cache_clear()
        >>> o1 = get_opener()
        >>> o1 is get_opener()
        True
        >>> o1 is get_opener(encoding='utf-8')
        False
        >>> get_opener.cache_info().hits
        1
        >>> o2 = get_opener(memoize=True)
        >>> o2 is get_opener(memoize=True)
        True
        >>> get_opener.cache_info().hits
        2

    """
    wrapper = partial(opener, memoize=memoize, **kwargs)
    current_opener = wraps(opener)(wrapper)

    if memoize:
        kwargs.setdefault("cache_type", get_cache_type(spread=False))
        return mezmorize.memoize(**kwargs)(current_opener)

    return current_opener


class Fetch[B: (Literal[True], Literal[False])]:
    binary: B

    @overload
    def __init__(  # noqa: E704
        self: "Fetch[Literal[True]]",
        url: str = ...,
        *,
        binary: Literal[True],
        **kwargs: BasicArg,
    ) -> None: ...
    @overload  # noqa: E301
    def __init__(  # noqa: E704
        self: "Fetch[Literal[False]]",
        url: str = ...,
        *,
        binary: Literal[False] = ...,
        **kwargs: BasicArg,
    ) -> None: ...
    def __init__(  # noqa: E301
        self,
        url: str = "",
        *,
        memoize: BasicArg = False,
        binary: bool = False,
        **kwargs: BasicArg,
    ):
        # TODO: need to use separate timeouts for memoize and urlopen
        self.binary = binary  # pyright: ignore[reportAttributeAccessIssue]
        self.content_type = None
        self.file = None
        opener = get_opener(memoize=bool(url and memoize), binary=binary, **kwargs)

        try:
            self.file, self.content_type = opener(url)
        except URLError as e:
            if "File name too long" in str(e.reason):
                raise
            logger.error(f"Error opening {url}: {e.reason}")

    def __getattr__(self, name: str):
        if self.file is not None:
            return getattr(self.file, name)
        raise AttributeError(name)

    def close(self):
        if self.file:
            self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @overload
    def __iter__(self: "Fetch[Literal[True]]") -> Iterator[bytes]: ...  # noqa: E704
    @overload
    def __iter__(self: "Fetch[Literal[False]]") -> Iterator[str]: ...  # noqa: E704
    def __iter__(self) -> Iterator[bytes | str]:  # noqa: E301
        if self.file:
            result = iter(self.file)
        elif self.binary:
            result = iter([b""])
        else:
            result = iter([""])

        return result

    @overload
    def __next__(self: "Fetch[Literal[True]]") -> bytes: ...  # noqa: E704
    @overload
    def __next__(self: "Fetch[Literal[False]]") -> str: ...  # noqa: E704
    def __next__(self) -> bytes | str:  # noqa: E301
        if self.file:
            return next(self.file)

        raise StopIteration

    @overload
    def read(self: "Fetch[Literal[True]]", size: int = ...) -> bytes: ...  # noqa: E704
    @overload
    def read(self: "Fetch[Literal[False]]", size: int = ...) -> str: ...  # noqa: E704
    def read(self, size: int = -1) -> bytes | str:  # noqa: E301
        if self.file and size < 0:
            result = self.file.read()
        elif self.file:
            result = self.file.read(size)
        else:
            result = b"" if self.binary else ""

        return result

    @property
    def ext(self):
        if not self.content_type:
            ext = None
        elif "xml" in self.content_type:
            ext = "xml"
        elif "json" in self.content_type:
            ext = "json"
        else:
            ext = self.content_type.split("/")[1].split(";")[0]

        return ext


def _resolve_uncastable(
    value: Mapping | Sequence | PrimitiveValue,
    msg: str,
    default: SortableValue,
) -> SortableValue | None:
    if isinstance(value, (str, int, struct_time)):
        msg += ". Returning value without casting."
        logger.warning(msg)
        casted = value
    elif isinstance(value, (dict, CaseInsensitiveDict, list, tuple, Mapping, Sequence)):
        msg += ". Returning default value."
        logger.warning(msg)
        casted = default
    else:
        msg += ". Returning value without casting."
        logger.warning(msg)
        casted = value

    return casted


def _warn_and_default(type_name: str, default: SortableValue) -> SortableValue:
    msg = f"Received non-sortable {type_name} value. Returning default instead."
    logger.warning(msg)
    return default


def _resolve_default(
    _type: str | None, invalid_type: bool | None, default: PrimitiveValue | None
) -> SortableValue:
    resolved = ""

    if invalid_type and default is None:
        logger.warning(f"Invalid cast type={_type}. Setting default to empty string.")
    elif _type and default is None:
        _default = CAST_SWITCH[_type].get("default")
        resolved = cast_type(PrimitiveValue, _default) or ""
    elif isinstance(default, Mapping):
        logger.warning(f"Invalid {default=}. Setting to empty string.")
    elif default is not None:
        resolved = default

    return resolved


def def_itemgetter(
    attr: str, default: PrimitiveValue | None = None, _type: str | None = None
) -> Callable[[Mapping | PrimitiveValue], SortableValue]:
    # like operator.itemgetter but fills in missing keys with a default value
    _invalid_type = _type in {CastType.LOCATION, CastType.NONE}
    invalid_type = bool(_invalid_type or (_type and _type not in CAST_SWITCH))
    default = _resolve_default(_type, invalid_type, default)

    _invalid_type = _type in {CastType.LOCATION, CastType.PASS, CastType.NONE}
    invalid_type = _invalid_type or (_type and _type not in CAST_SWITCH)

    def keyfunc(item: Mapping | PrimitiveValue) -> SortableValue:
        if isinstance(item, (dict, CaseInsensitiveDict, Mapping)):
            value = item.get(attr, default)
        else:
            value = item

        msg = f"Invalid cast type={_type} for key '{attr}'."

        if invalid_type:
            casted = _resolve_uncastable(value, msg, default)
        elif _type:
            _casted = cast_value(value, CastType(_type))
            casted = cast_type(PrimitiveValue, _casted)
        elif isinstance(value, (str, int, struct_time)):
            casted = value
        elif isinstance(value, NON_SORTABLE):
            casted = _warn_and_default(type(value).__name__, default)
        elif value is not None:
            casted = value
        else:
            casted = default

        if casted is None or (isinstance(casted, (float, Decimal)) and isnan(casted)):
            casted = default

        return casted

    return keyfunc


# TODO: move this to meza.process.group
def group_by[T: Mapping | PrimitiveValue](
    content: Iterable[T], attr: str, default=None
) -> ItemsView[str, list[T]]:
    keyfunc = def_itemgetter(attr, default)
    groups: dict[str, list[T]] = {}

    for item in content:
        if isinstance(item, (Mapping, str, int)):
            key = str(keyfunc(item))
        else:
            key = str(item)

        groups.setdefault(key, []).append(item)

    return groups.items()


@overload
def unique_everseen[T](content: Iterable[T]) -> Iterator[T]: ...  # noqa: E704
@overload  # noqa: E302
def unique_everseen[T](  # noqa: E704
    content: Iterable[T], keyfunc: Callable
) -> Iterator[str]: ...
def unique_everseen[T](  # noqa: E302
    content: Iterable[T], keyfunc: Callable | None = None
) -> Iterator[str | T]:
    # List unique elements, preserving order. Remember all elements ever seen
    # unique_everseen('ABBcCaD', str.lower) --> a b c d
    seen = set()

    for element in content:
        k = str(keyfunc(element)) if keyfunc else element

        if k not in seen:
            seen.add(k)
            yield k


def betwix(iterable, start=None, stop=None, inc=False):
    """
    Extract selected elements from an iterable. But unlike `islice`,
    extract based on the element's value instead of its position.

    Args:
        iterable (iter): The initial sequence
        start (str): The fragment to begin with (inclusive)
        stop (str): The fragment to finish at (exclusive)
        inc (bool): Make stop operate inclusively (useful if reading a file and
            the start and stop fragments are on the same line)

    Returns:
        Iter: New dict with specified keys removed

    Examples:
        >>> from io import StringIO
        >>>
        >>> list(betwix('ABCDEFG', stop='C'))
        ['A', 'B']
        >>> list(betwix('ABCDEFG', 'C', 'E'))
        ['C', 'D']
        >>> list(betwix('ABCDEFG', 'C'))
        ['C', 'D', 'E', 'F', 'G']
        >>> f = StringIO('alpha\\n<beta>\\ngamma\\n')
        >>> list(betwix(f, '<', '>', True))
        ['<beta>\\n']
        >>> list(betwix('ABCDEFG', 'C', 'E', True))
        ['C', 'D', 'E']

    """

    def inc_takewhile(predicate, _iter):
        for x in _iter:
            yield x

            if not predicate(x):
                break

    get_pred = lambda sentinel: lambda x: sentinel not in x
    pred = get_pred(stop)
    first = it.dropwhile(get_pred(start), iterable) if start else iterable

    if stop and inc:
        last = inc_takewhile(pred, first)
    elif stop:
        last = it.takewhile(pred, first)
    else:
        last = first

    return last


def dispatch[T, VT](split: Sequence[VT], *funcs: Callable[[VT], T]) -> tuple[T, ...]:
    r"""
    Takes a tuple of items and delivers each one to a different function

    Differs from `map` which applies multiple items to the same function.

           /--> item1 --> double(item1) -----> \
          /                                     \
    split ----> item2 --> oct(item2) ------->   _OUTPUT
          \                                     /
           \--> item3 --> max(item3) --------> /

    One way to construct such a flow in code would be::

    Example:
    >>> split = (3, 8365641317588141140, ['a', 'b', 'r'])
    >>> double = lambda item: item * 2
    >>> _OUTPUT = dispatch(split, double, oct, max)
    >>> _OUTPUT
    (6, '0o720305647221513002124', 'r')

    """
    # split = list(split)
    # for item, func in zip(split, funcs):
    #     v = func(item)
    #     print(f"dispatch: {func}({item}) = {v}")

    return tuple(func(item) for item, func in zip(split, funcs, strict=False))


def broadcast[T, VT](item: VT, *funcs: Callable[[VT], T], **kwargs) -> tuple[T, ...]:
    r"""
    Delivers the same item to different functions.

    Differs from `map` which applies multiple items to the same function.

           /--> item --> len(item) --------> \
          /                                   \
    item -----> item --> hash(item) ------->  split
          \                                   /
           \--> item --> sorted(item) -----> /

    One way to construct such a flow in code would be::

    Example:
    >>> split = broadcast('bar', len, hash, sorted)
    >>> split
    (3, -6516517828960271057, ['a', 'b', 'r'])

    """
    return tuple(func(item, **kwargs) for func in funcs)


def _gen_words(match, splits: Iterable[BasicValue]):
    groups = list(it.dropwhile(lambda x: not x, match.groups()))

    for s in splits:
        try:
            num = int(s)
        except ValueError:
            word = s
        else:
            word = next(it.islice(groups, num, num + 1))

        yield word


def multi_substitute(word: str, rules):
    """
    Apply multiple regex rules to 'word'
    http://code.activestate.com/recipes/
    576710-multi-regex-single-pass-replace-of-multiple-regexe/
    """
    flags = rules[0]["flags"]

    # Create a combined regex from the rules
    tuples = ((p, r["match"]) for p, r in enumerate(rules))
    regexes = (f"(?P<match_{p}>{r})" for p, r in tuples)
    pattern = "|".join(regexes)
    regex = re.compile(pattern, flags)
    resplit = re.compile("\\$(\\d+)")

    # For each match, look-up corresponding replace value in dictionary
    rules_in_series = filter(itemgetter("series"), rules)
    rules_in_parallel = (r for r in rules if not r["series"])

    try:
        has_parallel = [next(rules_in_parallel)]
    except StopIteration:
        has_parallel = []

    # print('================')
    # pprint(rules)
    # print('word:', word)
    # print('pattern', pattern)
    # print('flags', flags)

    for _ in it.chain(rules_in_series, has_parallel):
        # print('~~~~~~~~~~~~~~~~')
        # print('new round')
        # print('word:', word)
        # found = list(regex.finditer(word))
        # matchitems = [match.groupdict().items() for match in found]
        # pprint(matchitems)
        prev_name = None
        prev_is_series = None
        i = 0

        for match in regex.finditer(word):
            items = match.groupdict().items()
            item = next(filter(itemgetter(1), items))

            # print('----------------')
            # print('groupdict:', match.groupdict().items())
            # print('item:', item)

            if not item:
                continue

            name = item[0]
            rule = rules[int(name[6:])]
            series = rule.get("series")
            kwargs = {"count": rule["count"], "series": series}
            is_previous = name == prev_name
            singlematch = kwargs["count"] == 1
            is_series = prev_is_series or kwargs["series"]
            isnt_previous = bool(prev_name) and not is_previous

            if (is_previous and singlematch) or (isnt_previous and is_series):
                continue

            prev_name = name
            prev_is_series = series

            if resplit.findall(rule["replace"]):
                splits = resplit.split(rule["replace"])
                words = _gen_words(match, splits)
            else:
                splits = rule["replace"]
                start = match.start() + i
                end = match.end() + i
                words = [word[:start], splits, word[end:]]
                i += rule["offset"]

            word = "".join(words)

            # print('name:', name)
            # print('prereplace:', rule['replace'])
            # print('splits:', splits)
            # print('resplits:', resplit.findall(rule['replace']))
            # print('groups:', filter(None, match.groups()))
            # print('i:', i)
            # print('words:', words)
            # print('range:', match.start(), '-', match.end())
            # print('replace:', word)

    # print('substitution:', word)
    return word


def substitute(word: str, rule):
    if word:
        result = rule["match"].subn(rule["replace"], word, rule["count"])
        replaced, replacements = result

        if rule.get("default") is not None and not replacements:
            replaced = rule.get("default")
    else:
        replaced = word

    return replaced


def make_regex_rule(
    f: str, m: str, r: str, seriesmatch: bool = True, default=None
) -> RegexConfRule:
    return RegexConfRule(
        field=f, match=m, replace=r, seriesmatch=seriesmatch, default=default
    )


# @memoize(TIMEOUT)
def get_regex_rule(rule: Objconf | RegexConfRule, recompile=False) -> RegexRule:
    rule = rule if is_dataclass(rule) else RegexConfRule(**rule)
    flags = 0 if rule.casematch else re.IGNORECASE

    if not rule.singlelinematch:
        flags |= re.MULTILINE
        flags |= re.DOTALL

    count: int = 1 if rule.singlelinematch else 0

    if recompile and "$" in rule.replace:
        replace = re.sub(r"\$(\d+)", r"\\\1", rule.replace, count=0)
    else:
        replace = rule.replace

    match = re.compile(rule.match, flags) if recompile else rule.match

    nrule = {
        "count": count,
        "flags": flags,
        "match": match,
        "replace": replace,
        "default": rule.default,
        "field": rule.field,
        "offset": rule.offset or 0,
        "series": rule.seriesmatch,
    }

    return RegexRule(**nrule)


def multiplex[T](sources: Iterable[Iterable[T]]) -> Iterable[T]:
    """Combine multiple generators into one"""
    return it.chain.from_iterable(sources)


def augment_entries(entries: Iterable[ParserRSSEntry]) -> Iterator[RSSEntry]:
    for entry in entries:
        pub_date = updated_date = None

        if "summary" not in entry:
            entry["summary"] = entry["description"]

        if "published_parsed" in entry:
            pub_date = updated_date = entry["published_parsed"]
        elif "published" in entry:
            pub_date = updated_date = entry["published"]

        if pub_date:
            pub_date = ensure_tzinfo(pub_date)

            if isinstance(pub_date, datetime.datetime):
                pub_date = pub_date.timetuple()

        if "updated_parsed" in entry:
            updated_date = entry["updated_parsed"]
        elif "updated" in entry:
            updated_date = entry["updated"]

        if updated_date:
            updated_date = ensure_tzinfo(updated_date)

            if isinstance(updated_date, datetime.datetime):
                updated_date = updated_date.timetuple()

        entry["author.name"] = entry.get("author_detail", {}).get("name")
        entry["author.uri"] = entry.get("author_detail", {}).get("href")
        entry["dc:creator"] = entry.get("author")
        entry["y:id"] = entry.get("id")
        entry["updated_parsed"] = updated_date
        entry["published_parsed"] = entry["y:published"] = entry["pubDate"] = pub_date
        entry["y:title"] = entry.get("title")
        yield cast(RSSEntry, entry)


@overload
def gen_items(content: RikoValue) -> ValueStream: ...  # noqa: E704
@overload  # noqa: E302
def gen_items(  # noqa: E704
    content: RikoValue, key: str, yield_if_none: bool = ...
) -> Stream: ...  # noqa: E704
@overload  # noqa: E302
def gen_items(  # noqa: E704
    content: RikoValue, key: None = ..., yield_if_none: bool = ...
) -> ValueStream: ...
def gen_items(  # noqa: E302
    content: RikoValue, key: str | None = None, yield_if_none=False
) -> StreamOrValueStream:
    if isinstance(content, (struct_time, dict, CaseInsensitiveDict)):
        yield {key: cast(BasicDict, content)} if key else content
    elif isinstance(content, (list, tuple)):
        for value in content:
            yield from gen_items(value, key)
    elif content is not None or yield_if_none:
        yield {key: content} if key else content


def send(target: str, item: Item | StatefulItem):
    if target in _registry:
        _registry[target].send(item)
    else:
        logger.error(f"Attempted to send {item} to non-existent '{target}'")


def close(name: str):
    if gen := _registry.get(name):
        gen.close()


def coroutine(registry_name: str | None = None, maxlen=256):
    """Decorator for generator-based coroutines."""

    def decorator(
        func: Callable[..., Generator[None, Item | StatefulItem, None]],
    ):
        name = registry_name or func.__name__

        @wraps(func)
        def wrapper(*args, **kwargs):
            gen = func(*args, **kwargs)
            next(gen)
            _registry[name] = gen
            _receive_queue[name] = deque(maxlen=maxlen)
            return gen

        return wrapper

    return decorator


def gen_dependencies(pipe_def: PipeDef) -> Iterator[str]:
    for module in pipe_def["modules"]:
        yield module["type"]


def extract_dependencies(
    pipe_def: PipeDef | None = None, pipeline: PipelineDependencies | None = None
) -> list[str]:
    """Extract modules used by a pipe"""
    if pipe_def:
        pydeps = gen_dependencies(pipe_def)
    elif pipeline:
        pydeps = pipeline(Context(describe_dependencies=True))
    else:
        raise TypeError("Must supply at least one kwarg!")

    return sorted(set(pydeps))


def gen_input(pipe_def: PipeDef) -> Iterator[tuple[str]]:
    fields = ["position", "name", "prompt"]

    for module in pipe_def["modules"]:
        # Note: there seems to be no need to recursively collate inputs
        # from subpipelines
        try:
            module_confs = [module["conf"][x]["value"] for x in fields]
        except (KeyError, TypeError):
            pass
        else:
            values = ["type", "value"]
            module_confs.extend(module["conf"]["default"][x] for x in values)
            yield tuple(module_confs)


def get_input(conf: InputRawConf, **kwargs):
    """
    Gets a user parameter, either from the console or from an outer
     submodule/system

    Assumes conf has name, default, prompt and debug
    """
    name = conf["name"]["value"]
    prompt = conf["prompt"]["value"]
    _default = conf.get("default") or conf.get("debug") or {}
    default = _default.get("value")

    if inputs := kwargs.get("inputs"):
        value = inputs.get(name, default)
    elif not kwargs.get("test"):
        # we skip user interaction during tests
        raw = input(f"{prompt} (default={default}) ")
        value = raw or default
    else:
        value = default

    return value


def extract_input(
    pipe_def: PipeDef | None = None, pipeline: PipelineDependencies | None = None
) -> Sequence[str | tuple[str]]:
    """Extract inputs required by a pipe"""
    if pipe_def:
        pyinput = gen_input(pipe_def)
    elif pipeline:
        pyinput = pipeline(Context(describe_input=True))
    else:
        raise TypeError("Must supply at least one kwarg!")

    return sorted(pyinput)


def pythonise(
    content: str | Mapping,
    encoding="ascii",
    replace: Sequence[str] = ("-", ":", "/", ""),
    key: str | None = None,
) -> str:
    """Return a Python-friendly id"""
    if not isinstance(content, str):
        if key:
            resolved = DotDict(content).get(key)

            if isinstance(resolved, str):
                content = resolved
            elif isinstance(resolved, (Mapping, Sequence)):
                _type = type(resolved).__name__
                raise TypeError(f"Key '{key}' resolved to unsupported type {_type}.")
            else:
                content = str(resolved)
        else:
            raise ValueError("Received a dict without a key.")
    elif key:
        raise ValueError("Received a key without a dict.")

    reduced = reduce(replacer, replace, content)
    return reduced.encode(encoding, "replace").decode(encoding)


def gen_names(
    module_ids: Sequence[str] | Sequence[tuple[str, ...]],
    parsed_pipe_def: ParsedPipeDef,
    ntype="module",
) -> Iterator[str]:
    for module_id in module_ids:
        if isinstance(module_id, str):
            module_id = (module_id,)

        for _module_id in module_id:
            module_type = parsed_pipe_def["modules"][_module_id]["type"]

            if module_type.startswith("pipe:"):
                name = pythonise(module_type)
            elif ntype == "module":
                name = module_type
            elif ntype == "pipe":
                name = "pipe"
            else:
                raise ValueError(f"Invalid {ntype=}. (Expected 'module' or 'pipe')")

            yield name


def gen_modules(
    pipe_def: PipeDef, embedded=False
) -> Iterator[tuple[str, PipeModule] | tuple[str, EmbeddedModule]]:
    for module in listize(pipe_def["modules"]):
        yield (pythonise(module["id"]), module)

        if embedded and module["type"] == "loop":
            conf = cast_type(LoopRawConf, module["conf"])
            embed = conf["embed"]["value"]
            yield (pythonise(embed["id"]), embed)


def gen_wires(pipe_def: PipeDef) -> Iterator[tuple[str, Wire]]:
    for wire in pipe_def["wires"]:
        yield (pythonise(wire["id"]), wire)


def gen_graph(pipe_def: PipeDef) -> Iterator[tuple[str, str]]:
    for wire in pipe_def["wires"]:
        src_id = pythonise(wire["src"]["moduleid"])
        tgt_id = pythonise(wire["tgt"]["moduleid"])
        yield (src_id, tgt_id)


def gen_embed_graph(pipe_def: PipeDef) -> Iterator[tuple[str, list]]:
    for module in listize(pipe_def["modules"]):
        module_id = pythonise(module["id"])
        yield (module_id, [])

        # make the loop dependent on its embedded module
        if module["type"] == "loop":
            conf = cast_type(LoopRawConf, module["conf"])
            embed = conf["embed"]["value"]
            yield (pythonise(embed["id"]), [module_id])


def gen_parented_graph(graph):
    """Remove any orphan nodes"""
    for node, value in graph.items():
        if value or any(node in v for v in graph.values()):
            yield (node, value)


def truncate_content[T](content: T | object, length: int = 20) -> T:
    if isinstance(content, str):
        truncated = content[:length] + "…" if len(content) > length else content
    elif isinstance(content, (dict, CaseInsensitiveDict, Mapping)):
        truncated = {k: truncate_content(v) for k, v in content.items()}
    elif isinstance(content, (list, tuple, Sequence)):
        truncated = [truncate_content(v) for v in content]
    else:
        truncated = content

    return cast(T, truncated)
