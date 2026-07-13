# vim: sw=4:ts=4:expandtab
"""
riko.pprint2
~~~~~~~~~~~~
Provides function pretty printing
"""

from collections.abc import Mapping, Sequence
from functools import total_ordering

from riko.types.general import BasicArg


def cmp(a, b):
    return (a > b) - (a < b)


@total_ordering
class Id:
    """An object that is not quoted as literal by repr"""

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return str(self.name)

    def __lt__(self, other):
        if isinstance(other, Id):
            return cmp(self.name, other.name)
        else:
            return -1

    def __eq__(self, other):
        if isinstance(other, Id):
            return self.name == other.name
        else:
            return False


def repr_args(args):
    """
    Formats a list of function arguments prettily but as working code

    (kwargs are tuples (argname, argvalue)
    """
    res = []
    for x in args:
        if isinstance(x, tuple) and len(x) == 2:
            key, value = x
            # todo: exclude this key if value is its default
            res += [f"{key}={repr_arg(value)}"]
        else:
            res += [repr_arg(x)]
    return ", ".join(res)


def repr_arg(d: BasicArg) -> str:
    """
    Formats a function argument prettily but as working code

    unicode encodable as ascii is formatted as str
    """
    if isinstance(d, Mapping):
        # if d can be expressed in key=value syntax:
        joined = ", ".join(f"{repr_arg(k)}: {repr_arg(v)}" for k, v in d.items())
        value = f"{joined}"
    elif isinstance(d, str):
        try:
            value = repr(d.encode("ascii"))
        except (UnicodeEncodeError, AttributeError):
            value = repr(d)
    elif isinstance(d, Sequence):
        value = f"[{', '.join(repr_arg(elem) for elem in d)}]"
    elif d is not None:
        print(f"Unsupported type {type(d)} for argument {d}")
        value = str(d)
    else:
        value = ""

    return value


def str_args(args):
    """
    Formats a list of function arguments prettily not as code

    (kwargs are tuples (argname, argvalue)
    """
    res = []

    for x in args:
        if isinstance(x, str):
            res.append(x)
        elif isinstance(x, Sequence) and len(x) == 2:
            key, value = x

            if value and (str_value := str_arg(value)):
                res.append(f"{key}={str_value}")
        else:
            res.append(str_arg(x))
    return ", ".join(res)


def str_arg(d):
    """
    Formats a function argument prettily not as code

    dicts are expressed in {key=value} syntax
    strings are formatted using str in quotes not repr
    """
    if not d:
        return None

    if isinstance(d, Mapping):
        if len(d) == 2 and d.get("type") == "text" and "value" in d:
            return str_arg(d["value"])
        if len(d) == 2 and d.get("type") == "text" and "subkey" in d:
            return ".{subkey}".format(**d)
        if d.get("type") == "module":
            return None
        return f"{0}".format(str_args(d.items()))
    elif isinstance(d, str):
        return f'"{d}"'
    elif isinstance(d, Sequence):
        if len(d) == 1:
            return str_arg(d[0])

        return "[{}]".format(", ".join(str_arg(elem) for elem in d))

    return repr(d)
