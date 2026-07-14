# vim: sw=4:ts=4:expandtab
"""
Provides function pretty printing
"""

from collections.abc import Mapping, Sequence
from functools import total_ordering
from time import struct_time


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


def repr_args(*args: object):
    """
    Formats a list of function arguments prettily but as working code
    """
    res = []
    for arg in args:
        if isinstance(arg, struct_time):
            res += [repr_arg(arg)]
        elif isinstance(arg, tuple) and len(arg) == 2:
            key, value = arg
            # todo: exclude this key if value is its default
            res += [f"{key}={repr_arg(value)}"]
        else:
            res += [repr_arg(arg)]

    return ", ".join(res)


def repr_arg(arg: object) -> str:
    """
    Formats a function argument prettily but as working code

    unicode encodable as ascii is formatted as str
    """
    if isinstance(arg, str):
        try:
            value = repr(arg.encode("ascii"))
        except (UnicodeEncodeError, AttributeError):
            value = repr(arg)
    elif isinstance(arg, dict):
        items = arg.items()
        joined = ", ".join(f"{repr_arg(k)}: {repr_arg(v)}" for k, v in items)
        value = f"{joined}"
    elif isinstance(arg, Mapping):
        joined = ", ".join(f"{repr_arg(k)}: {repr_arg(v)}" for k, v in arg.items())
        value = f"{joined}"
    elif isinstance(arg, Sequence):
        value = f"[{', '.join(repr_arg(elem) for elem in arg)}]"
    elif arg is not None:
        print(f"Unsupported type {type(arg)} for argument {arg}")
        value = str(arg)
    else:
        value = ""

    return value


def str_args(*args: object):
    """
    Formats a list of function arguments prettily not as code

    (kwargs are tuples (argname, argvalue)
    """
    res = []

    for arg in args:
        if isinstance(arg, (str, struct_time)):
            res.append(arg)
        elif isinstance(arg, tuple) and len(arg) == 2:
            key, value = arg

            if value and (str_value := str_arg(value)):
                res.append(f"{key}={str_value}")
        else:
            res.append(str_arg(arg))

    return ", ".join(res)


def str_arg(arg: object):
    """
    Formats a function argument prettily not as code

    dicts are expressed in {key=value} syntax
    strings are formatted using str in quotes not repr
    """
    if not arg:
        res = None
    elif isinstance(arg, str):
        res = f'"{arg}"'
    elif isinstance(arg, Mapping):
        if len(arg) == 2 and arg.get("type") == "text" and "value" in arg:
            res = str_arg(arg["value"])
        elif len(arg) == 2 and arg.get("type") == "text" and "subkey" in arg:
            res = ".{subkey}".format(**arg)
        elif arg.get("type") == "module":
            res = None
        elif isinstance(arg, dict):
            items = arg.items()
            res = f"{0}".format(str_args(*items))
        else:
            res = f"{0}".format(str_args(*arg.items()))
    elif isinstance(arg, Sequence):
        if len(arg) == 1:
            res = str_arg(arg[0])
        else:
            res = "[{}]".format(", ".join(map(str_arg, arg)))
    else:
        res = repr(arg) if arg else None

    return res
