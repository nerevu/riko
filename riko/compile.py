"""
Compile/Translate Yahoo Pipe into Python

Takes a JSON representation of a Yahoo pipe and either:
a) translates it into a Python script containing a function
(using generators to build the pipeline) or
b) compiles it as a pipeline of generators which can be executed
in-process

Usage:
a) compile tests/pipelines/testpipe1.json -o testpipe1.py
python testpipe1.py

b) from riko import compile

pipe_def = json.loads(pjson)
parsed_pipe_def = parse_pipe_def(pipe_def, pipe_name)
pipeline = build_pipeline(parsed_pipe_def)
print(list(pipeline))

Author: Greg Gaughan
Idea: Tony Hirst (http://ouseful.wordpress.com/2010/02/25/
starting-to-think-about-a-yahoo-pipes-code-generator)
Python generator pipelines inspired by:
David Beazely (http://www.dabeaz.com/generators-uk)
auto-rss module by Mark Pilgrim

License: see LICENSE file
"""

import builtins
import keyword
import subprocess
from codecs import open
from collections import defaultdict
from collections.abc import Awaitable, Iterable, Iterator, Mapping, Sequence
from datetime import date
from decimal import Decimal
from functools import reduce
from importlib import import_module
from inspect import isawaitable
from itertools import pairwise
from json import JSONEncoder, dumps, loads
from pathlib import Path
from pprint import PrettyPrinter
from time import struct_time
from typing import Any, Literal, cast, overload

from jinja2 import Environment, PackageLoader

from riko import Context, listize, replacer
from riko.context import ExecutionMode
from riko.dotdict import DotDict
from riko.exceptions import UnsupportedModuleError, UnsupportedPipelineError
from riko.modules._subpipe import is_subpipe, mark_subpipe
from riko.pprint2 import Id, repr_arg, repr_args
from riko.topsort import topological_sort
from riko.types.compile import (
    AbbrevStringModule,
    LoopModule,
    ParsedPipeDef,
    PipeDag,
    PipeDef,
    PipelineDescription,
    PipeModule,
    StringModule,
    TemplateData,
    Wire,
)
from riko.types.general import (
    AsyncPipeItems,
    AsyncPipelineDependencies,
    AsyncPipeParser,
    AsyncPyInput,
    AsyncStream,
    ParserOutput,
    Pipeline,
    PipelineDependencies,
    PyInput,
    Step,
    Steps,
    StepValue,
    Stream,
    SyncPipelineDependencies,
    SyncPipeParser,
    SyncPyInput,
)
from riko.types.modules import (
    AnyModuleRawConf,
    ConfArg,
    CountValues,
    EmbeddedModule,
    Graph,
    InputRawConf,
    Nodes,
    Value,
)
from riko.types.values import Inputs

_RAW_CONFS = {
    "count": "CountRawConf",
    "csv": "CsvRawConf",
    "currencyformat": "CurrencyFormatRawConf",
    "dateformat": "DateFormatRawConf",
    "exchangerate": "ExchangeRateRawConf",
    "feedautodiscovery": "FeedAutoDiscoveryRawConf",
    "fetch": "FetchRawConf",
    "fetchdata": "FetchDataRawConf",
    "fetchpage": "FetchPageRawConf",
    "fetchsitefeed": "FetchSiteFeedRawConf",
    "fetchtable": "FetchTableRawConf",
    "fetchtext": "FetchTextRawConf",
    "filter": "FilterRawConf",
    "geolocate": "GeolocateRawConf",
    "input": "InputRawConf",
    "itembuilder": "ItemBuilderRawConf",
    "join": "JoinRawConf",
    "loop": "LoopRawConf",
    "receive": "ReceiveRawConf",
    "refind": "RefindRawConf",
    "regex": "RegexRawConf",
    "rename": "RenameRawConf",
    "rssitembuilder": "RssItemBuilderRawConf",
    "send": "SendRawConf",
    "simplemath": "SimpleMathRawConf",
    "slugify": "SlugifyRawConf",
    "sort": "SortRawConf",
    "split": "SplitRawConf",
    "strconcat": "StrconcatRawConf",
    "strfind": "StrfindRawConf",
    "strreplace": "StrReplaceRawConf",
    "strtransform": "StrTransformRawConf",
    "subelement": "SubelementRawConf",
    "substr": "SubstrRawConf",
    "sum": "SumRawConf",
    "tail": "TailRawConf",
    "timeout": "TimeoutRawConf",
    "tokenizer": "TokenizerRawConf",
    "truncate": "TruncateRawConf",
    "typecast": "TypecastRawConf",
    "uniq": "UniqRawConf",
    "urlbuilder": "UrlBuilderRawConf",
    "urlparse": "UrlParseRawConf",
    "xpathfetchpage": "XpathFetchPageRawConf",
}


class MyPrettyPrinter(PrettyPrinter):
    def format(
        self, object: object, context: dict[int, int], maxlevels: int, level: int
    ) -> tuple[str, bool, bool]:
        if isinstance(object, bytes):
            object = object.decode("utf8")

        return super().format(object, context, maxlevels, level)


class CustomEncoder(JSONEncoder):
    def default(self, o: object) -> Any:
        if isinstance(o, (Decimal, date, struct_time)):
            result = str(o)
        elif isinstance(o, (Iterator, set)):
            result = list(o)
        else:
            result = super().default(o)

        return result


def gen_dependencies(pipe_def: PipeDef | ParsedPipeDef) -> Iterator[str]:
    modules = pipe_def["modules"]

    if isinstance(modules, dict):
        embed = pipe_def.get("embed") or {}
        modules = [module for key, module in modules.items() if key not in embed]

    for module in modules:
        dep = module if isinstance(module, str) else module["type"]

        if dep != "output":
            yield dep


@overload
def extract_dependencies(  # noqa: E704
    pipe_def: PipeDef | ParsedPipeDef | None = ...,
) -> list[str]: ...
@overload  # noqa: E302
def extract_dependencies(  # noqa: E704
    pipe_def: PipeDef | ParsedPipeDef | None = ...,
    *,
    pipeline: AsyncPipelineDependencies,
) -> Awaitable[list[str]]: ...
@overload  # noqa: E302
def extract_dependencies(  # noqa: E704
    pipe_def: PipeDef | ParsedPipeDef | None = ...,
    *,
    pipeline: SyncPipelineDependencies,
) -> list[str]: ...
def extract_dependencies(  # noqa: E302
    pipe_def: PipeDef | ParsedPipeDef | None = None,
    pipeline: PipelineDependencies | None = None,
) -> Awaitable[list[str]] | list[str]:
    """Extract modules used by a pipe"""
    if pipe_def:
        pydeps = gen_dependencies(pipe_def)
    elif pipeline:
        pydeps = pipeline(context=Context(mode=ExecutionMode.DESCRIBE_DEPENDENCIES))
    else:
        raise TypeError("Must supply at least one kwarg!")

    return pydeps if isawaitable(pydeps) else sorted(set(pydeps))


def gen_input(pipe_def: PipeDef | ParsedPipeDef) -> Iterator[tuple[str, ...]]:
    fields = ["position", "name", "prompt"]
    values = ["type", "value"]
    modules = pipe_def["modules"]

    if isinstance(modules, dict):
        embed = pipe_def.get("embed") or {}
        modules = [m for k, m in modules.items() if k not in embed]

    for module in modules:
        # Note: there seems to be no need to recursively collate inputs
        # from subpipelines
        conf = module["conf"]

        try:
            module_confs: list[str] = [conf[x]["value"] for x in fields]
        except (KeyError, TypeError):
            pass
        else:
            if default := conf.get("default"):
                module_confs.extend(default[x] for x in values)

            yield tuple(module_confs)


def get_input(conf: InputRawConf, **kwargs: object) -> str | int | bool:
    """
    Gets a user parameter, either from the console or from an outer
     submodule/system

    Assumes conf has name, default, prompt and debug
    """
    name = str(conf["name"]["value"])
    prompt = conf["prompt"]["value"]
    __default = ConfArg({"type": "text", "value": ""})
    _default = conf.get("default") or conf.get("debug") or __default
    default = _default.get("value")

    if inputs := kwargs.get("inputs"):
        value = cast(Inputs, inputs).get(name, default)
    elif not kwargs.get("test"):
        # we skip user interaction during tests
        raw = input(f"{prompt} (default={default}) ")
        value = raw or default
    else:
        value = default

    return value


@overload
def extract_input(  # noqa: E704
    pipe_def: PipeDef | ParsedPipeDef | None = ...,
) -> SyncPyInput: ...
@overload  # noqa: E302
def extract_input(  # noqa: E704
    pipe_def: PipeDef | ParsedPipeDef | None = ...,
    *,
    pipeline: AsyncPipelineDependencies,
) -> AsyncPyInput: ...
@overload  # noqa: E302
def extract_input(  # noqa: E704
    pipe_def: PipeDef | ParsedPipeDef | None = ...,
    *,
    pipeline: SyncPipelineDependencies,
) -> SyncPyInput: ...
def extract_input(  # noqa: E302
    pipe_def: PipeDef | ParsedPipeDef | None = None,
    pipeline: PipelineDependencies | None = None,
) -> PyInput:
    """Extract inputs required by a pipe"""
    if pipe_def:
        pyinput = gen_input(pipe_def)
    elif pipeline:
        pyinput = pipeline(Context(mode=ExecutionMode.DESCRIBE_INPUTS))
    else:
        raise TypeError("Must supply at least one kwarg!")

    return pyinput if isawaitable(pyinput) else sorted(pyinput)


def pythonise(
    content: str | Mapping[str, object],
    encoding: str = "ascii",
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
    ntype: Literal["module", "pipe", "async_pipe"] = "module",
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
            elif ntype in {"pipe", "async_pipe"}:
                name = ntype
            else:
                msg = f"Invalid {ntype=}. (Expected 'module', 'pipe', or 'async_pipe')"
                raise ValueError(msg)

            yield name


@overload
def gen_modules(  # noqa: E704
    pipe_def: PipeDef, embedded: Literal[False] = ...
) -> Iterator[tuple[str, PipeModule]]: ...
@overload  # noqa: E302
def gen_modules(  # noqa: E704
    pipe_def: PipeDef, embedded: Literal[True]
) -> Iterator[tuple[str, EmbeddedModule]]: ...
def gen_modules(  # noqa: E302
    pipe_def: PipeDef, embedded=False
) -> Iterator[tuple[str, PipeModule] | tuple[str, EmbeddedModule]]:
    for module in listize(pipe_def["modules"]):
        if embedded and module["type"] == "loop":
            embed = cast(LoopModule, module)["embed"]
            embedded_module = EmbeddedModule(
                {"id": embed["id"], "type": embed["type"], "conf": module["conf"]}
            )
            yield (pythonise(embedded_module["id"]), embedded_module)
        elif not embedded:
            yield (pythonise(module["id"]), module)


def gen_wires(pipe_def: PipeDef) -> Iterator[tuple[str, Wire]]:
    for wire in pipe_def["wires"]:
        yield (pythonise(wire["id"]), wire)


def gen_graph(pipe_def: PipeDef) -> Iterator[tuple[str, str]]:
    for wire in pipe_def["wires"]:
        src_id = pythonise(wire["src"]["moduleid"])
        tgt_id = pythonise(wire["tgt"]["moduleid"])
        yield (src_id, tgt_id)


def gen_embed_graph(pipe_def: PipeDef) -> Iterator[tuple[str, list[str]]]:
    for module in listize(pipe_def["modules"]):
        module_id = pythonise(module["id"])
        yield (module_id, [])

        # make the loop dependent on its embedded module
        if module["type"] == "loop":
            embed = cast(LoopModule, module)["embed"]
            yield (pythonise(embed["id"]), [module_id])


def gen_parented_graph[T: str | int](graph: Graph[T]) -> Iterator[tuple[T, Nodes[T]]]:
    """Remove any orphan nodes"""
    for node, value in graph.items():
        if value or any(node in v for v in graph.values()):
            yield (node, value)


def get_module_id(wire: Wire, stem: str = "src", base: str = "moduleid") -> str:
    return pythonise(wire, key=f"{stem}.{base}")


def write_file(
    data: object, path: Path | str | None, pretty: bool = False
) -> int | None:
    if data and path:
        with open(str(path), "w", encoding="utf-8") as f:
            if hasattr(data, "keys") and pretty:
                kwargs = {
                    "cls": CustomEncoder,
                    "sort_keys": True,
                    "indent": 4,
                    "ensure_ascii": False,
                }

                result = dumps(data, **kwargs)
            elif hasattr(data, "keys"):
                result = dumps(data, ensure_ascii=False)
            elif pretty:
                result = MyPrettyPrinter().pformat(data)
            else:
                result = str(data)

            return f.write(result)


def _module_alias(module_name: str) -> str:
    shadowed = module_name in dir(builtins) or keyword.iskeyword(module_name)
    return f"_{module_name}" if shadowed else module_name


def _lower_keys[T](obj: T) -> T:
    if isinstance(obj, dict):
        result = {
            (k.lower() if isinstance(k, str) and k.isupper() else k): _lower_keys(v)
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        result = [_lower_keys(v) for v in obj]
    else:
        result = obj

    return cast(T, result)


def _conf_source(module_name: str, conf: AnyModuleRawConf | Id | Context) -> str:
    raw = _RAW_CONFS.get(module_name)
    inner = repr_arg(conf)
    return f"{raw}({inner})" if raw else inner


def _render_conf(module_name: str, conf: AnyModuleRawConf | Id | Context) -> str:
    return _conf_source(module_name, _lower_keys(conf))


def _gen_embed_module_names(parsed_pipe_def: ParsedPipeDef) -> Iterator[str]:
    for module in parsed_pipe_def["modules"].values():
        if module["type"] == "loop":
            embed = cast(LoopModule, module)["embed"]

            if not embed["type"].startswith("pipe"):
                yield embed["type"]


def _gen_embed_subpipe_names(parsed_pipe_def: ParsedPipeDef) -> Iterator[str]:
    for module in parsed_pipe_def["modules"].values():
        if module["type"] == "loop":
            embed = cast(LoopModule, module)["embed"]

            if embed["type"].startswith("pipe"):
                yield pythonise(embed["type"])


def _get_sources(
    conf: AnyModuleRawConf | None,
) -> list[dict[str, str]] | None:
    if conf and (url := conf.get("url")) and isinstance(url, list):
        urls = cast(list[Value], url)
        return [{"url": cast(str, url["value"])} for url in urls]


def _used_raw_confs(parsed_pipe_def: ParsedPipeDef) -> set[str]:
    used = set()

    for module in parsed_pipe_def["modules"].values():
        conf = module["conf"]

        if _get_sources(conf) is not None:
            continue

        if module["type"] == "loop":
            embed = cast(LoopModule, module)["embed"]

            if embed_raw := _RAW_CONFS.get(embed["type"]):
                used.add(embed_raw)
        elif raw := _RAW_CONFS.get(module["type"]):
            used.add(raw)

    return used


def _render_args(
    module_name: str,
    pyarg: Id | None,
    pykwargs: Iterable[tuple[str, AnyModuleRawConf | Id | Context]],
) -> str:
    parts = []
    rendered = repr_arg(pyarg)

    if rendered:
        parts.append(rendered)

    for key, value in pykwargs:
        if key == "context":
            rendered_value = "context"
        elif key == "conf":
            rendered_value = _render_conf(module_name, value)
        else:
            rendered_value = repr_arg(value)

        if rendered_value:
            parts.append(f"{key}={rendered_value}")

    return ", ".join(parts)


def _gen_string_modules(
    parsed_pipe_def: ParsedPipeDef,
    module_ids: Iterable[str],
    module_names: Iterable[str],
    pipe_names: Iterable[str],
    context: Context | None = None,
    mode: ExecutionMode | None = None,
    inputs: Inputs | None = None,
    **kwargs: bool,
) -> Iterator[StringModule]:
    zipped = zip(module_ids, module_names, pipe_names, strict=False)
    context = context or Context(mode=mode, inputs=inputs, **kwargs)
    split_ids = defaultdict(int)
    checked = False

    for module_id, module_name, pipe_name in zipped:
        if module_id in parsed_pipe_def["embed"]:
            continue

        alias = _module_alias(module_name)
        args = (parsed_pipe_def, module_id)
        is_sub_pipe = module_name.startswith("pipe")
        pyarg = _get_pyarg(*args, split_ids=split_ids, steps=None, **kwargs)

        if not checked:
            pyarg = Id("item") if pyarg == Id(None) else pyarg
            checked = True

        conf = parsed_pipe_def["modules"][module_id]["conf"]
        sources = _get_sources(conf)

        if is_collection := sources is not None:
            expr = f"SyncCollection({repr_args(*sources)}, context=context)"
        elif module_name == "output":
            expr = repr_arg(pyarg)
        elif is_sub_pipe:
            pykwargs = list(_gen_pykwargs(*args, steps=None, **kwargs))
            expr = f"{pipe_name}({_render_args(module_name, None, pykwargs)})"
        else:
            pyarg_expr = repr_arg(pyarg)

            if split_ids and "_" in pyarg_expr:
                split_id = "_".join(pyarg_expr.split("_")[:-1])

                if split_id in split_ids:
                    split_ids[split_id] += 1

            module = parsed_pipe_def["modules"][module_id]

            if module["type"] == "loop" and "embed" in module:
                embed = cast(LoopModule, module)["embed"]
                embed_module_name = embed["type"]
            else:
                embed_module_name = module_name

            pykwargs = list(_gen_pykwargs(*args, steps=None, **kwargs))
            expr = f"{alias}({_render_args(embed_module_name, pyarg, pykwargs)})"

        if module_name == "split":
            splits = DotDict(conf).get("splits", 2)
            split_ids[module_id] = 0
        else:
            splits = 0

        yield StringModule(
            {
                "id": module_id,
                "expr": expr,
                "alias": alias,
                "is_sub_pipe": is_sub_pipe,
                "is_collection": is_collection,
                "name": module_name,
                "pipe_name": pipe_name,
                "splits": splits,
            }
        )


@overload
def _get_pyarg(  # noqa: E704
    *args: Any, steps: None = ..., **kwargs: Any
) -> Id: ...
@overload  # noqa: E302
def _get_pyarg(  # noqa: E704
    *args: Any, steps: Steps, **kwargs: Any
) -> ParserOutput | SyncPipeParser: ...
@overload  # noqa: E302
def _get_pyarg(  # noqa: E704
    *args: Any, **kwargs: Any
) -> ParserOutput | SyncPipeParser | Id: ...
def _get_pyarg(  # noqa: E302
    parsed_pipe_def: ParsedPipeDef,
    module_id: str,
    *,
    split_ids: Mapping[str, int] | None = None,
    steps: Steps | None = None,
    context: Context | None = None,
    mode: ExecutionMode | None = None,
    inputs: Inputs | None = None,
    **kwargs: bool,
) -> StepValue | Id | None:
    context = context or Context(mode=mode, inputs=inputs, **kwargs)
    split_ids = split_ids or {}

    if steps and context.mode is not ExecutionMode.RUN:
        print("You must not specify both describe and steps. Assuming steps.")

    return _get_input_module(parsed_pipe_def, module_id, steps, **split_ids)


def _is_default(wire: Wire, module_id: str, in_and_out: bool = False) -> bool:
    id_match = get_module_id(wire, stem="tgt") == module_id
    default_out = id_match and wire["src"]["id"].startswith("_OUTPUT")
    is_input = wire["tgt"]["id"] == "_INPUT"
    return default_out and (is_input if in_and_out else not is_input)


@overload
def _gen_pykwargs(  # noqa: E704
    parsed_pipe_def: ParsedPipeDef, module_id: str, steps: None = ..., **kwargs: Any
) -> Iterator[tuple[str, Id | Context | AnyModuleRawConf]]: ...
@overload  # noqa: E302
def _gen_pykwargs(  # noqa: E704
    parsed_pipe_def: ParsedPipeDef, module_id: str, steps: Steps, **kwargs: Any
) -> Iterator[tuple[str, StepValue | Context | AnyModuleRawConf]]: ...
def _gen_pykwargs(  # noqa: E302
    parsed_pipe_def: ParsedPipeDef,
    module_id: str,
    steps: Steps | None = None,
    context: Context | None = None,
    mode: ExecutionMode | None = None,
    inputs: Inputs | None = None,
    **kwargs: bool,
) -> Iterator[tuple[str, StepValue | Id | Context | AnyModuleRawConf]]:
    module = parsed_pipe_def["modules"][module_id]
    yield ("conf", module["conf"])

    for key in ("emit", "assign", "field", "count"):
        if (setting := module.get(key)) is not None:
            yield (key, cast(bool | str | CountValues, setting))

    context = context or Context(mode=mode, inputs=inputs, **kwargs)
    yield ("context", context)

    if steps and context.mode is not ExecutionMode.RUN:
        print("You must not specify both describe and steps. Assuming steps.")

    others = []

    # find the default input of this module
    for wire in parsed_pipe_def["wires"].values():
        # if the wire is to this module and it's *NOT* the default input
        # but it *is* the default output
        if _is_default(wire, module_id):
            src_module_id = get_module_id(wire)
            source = Id(src_module_id) if steps is None else steps[src_module_id]
            pipe_id = get_module_id(wire, stem="tgt", base="id")

            if pipe_id.startswith("_OTHER"):
                others.append(source)
            else:
                yield (pipe_id, source)

    if others:
        yield ("others", others)

    if module["type"] == "loop":
        embed = cast(LoopModule, module)["embed"]
        embed_type = embed["type"]
        pipe_id = pythonise(embed["id"])

        if steps is None:
            is_pipe = embed_type.startswith("pipe:")
            name = pythonise(embed_type) if is_pipe else _module_alias(embed_type)
            updated = Id(name)
        else:
            updated = steps[pipe_id]

        yield ("embed", updated)


@overload
def resolve_module(  # noqa: E704
    module_name: str,
    pipe_name: Literal["pipe"],
    compile_missing: Literal[False] = ...,
    file_path: Path | None = ...,
) -> SyncPipeParser: ...
@overload  # noqa: E302
def resolve_module(  # noqa: E704
    module_name: str,
    pipe_name: Literal["async_pipe"],
    compile_missing: Literal[False] = ...,
    file_path: Path | None = ...,
) -> AsyncPipeParser: ...
@overload  # noqa: E302
def resolve_module(  # noqa: E704
    module_name: str,
    pipe_name: str,
    compile_missing: Literal[False] = ...,
    file_path: Path | None = ...,
) -> Pipeline: ...
@overload  # noqa: E302
def resolve_module(  # noqa: E704
    module_name: str,
    pipe_name: str,
    compile_missing: Literal[True],
    file_path: Path | None = ...,
) -> tuple[Pipeline | None, ParsedPipeDef | None]: ...
def resolve_module(  # noqa: E302
    module_name: str,
    pipe_name: str,
    compile_missing=False,
    file_path: Path | None = None,
) -> Pipeline | None | tuple[Pipeline | None, ParsedPipeDef | None]:
    """
    Examples:
        >>> resolve_module('filter', 'pipe')
        <function pipe at ...>
        >>> resolve_module('does_not_exist', 'pipe')
        Traceback (most recent call last):
            ...
        riko.exceptions.UnsupportedModuleError: Unsupported riko module: does_not_exist

        Re-raises ModuleNotFoundError errors *inside* a valid module instead of masking
        it as an unsupported module:

        >>> import riko.compile as _c
        >>> _orig = _c.import_module
        >>> _c.import_module = lambda name: _orig("missing.submodule")
        >>> resolve_module('filter', 'pipe')
        Traceback (most recent call last):
            ...
        ModuleNotFoundError: No module named 'missing'
        >>> _c.import_module = _orig

    """
    module = parsed_pipe_def = None

    if module_name.startswith("pipe_"):
        try:
            module = import_module(f"tests.pypipelines.{module_name}")
        except ModuleNotFoundError as e:
            if compile_missing:
                msg = f"Couldn't import module for {pipe_name}: {e}. "
                msg += "Building from json..."
                print(msg)

                parent = Path(__file__).parent.parent
                file_path = file_path or parent / "tests" / "pipelines"
                pipe_file_name = file_path / f"{pipe_name}.json"

                try:
                    with pipe_file_name.open() as f:
                        pipe_def = loads(f.read())
                except OSError as file_error:
                    raise UnsupportedPipelineError(pipe_name) from file_error

                parsed_pipe_def = parse_pipe_def(pipe_def, pipe_name)
            else:
                raise UnsupportedPipelineError(pipe_name) from e
    else:
        target = f"riko.modules.{module_name}"

        try:
            module = import_module(target)
        except ModuleNotFoundError as e:
            if e.name != target:
                raise

            raise UnsupportedModuleError(module_name) from e

    pipeline = getattr(module, pipe_name, None) if module else None

    if module and pipeline is None:
        raise UnsupportedModuleError(f"{module_name!r} has no {pipe_name!r}")

    is_pipe = module_name.startswith("pipe_")

    if pipeline is not None and is_pipe and not is_subpipe(pipeline):
        no_input = parsed_pipe_def is None or not extract_input(parsed_pipe_def)
        mark_subpipe(pipeline, subtype="source" if no_input else "transformer")

    return (pipeline, parsed_pipe_def) if compile_missing else pipeline


def _gen_steps(
    parsed_pipe_def: ParsedPipeDef,
    *,
    module_ids: Iterable[str],
    module_names: Iterable[str],
    pipe_names: Iterable[str],
    steps: Steps | None = None,
    context: Context | None = None,
    **kwargs: bool,
) -> Iterator[Step]:
    zipped = zip(module_ids, module_names, pipe_names, strict=False)
    steps = steps or {}

    for module_id, module_name, pipe_name in zipped:
        args = (parsed_pipe_def, module_id)

        if module_name == "output":
            # Terminal sink marker: its result is just its input stream.
            pyarg = _get_pyarg(*args, steps=steps, context=context, **kwargs)
            step = (module_id, pyarg)
        elif module_id in parsed_pipe_def["embed"]:
            # We need to wrap submodules (used by loops) so we can pass the
            # input at runtime (as we can to sub-pipelines)
            # Note: no embed (so no subloops) or wire pykwargs are passed
            pipeline = resolve_module(module_name, pipe_name)
            pipeline.__name__ = str(f"pipe_{module_id}")
            step = (module_id, pipeline)
        else:  # else this module is not embedded:
            pipeline = resolve_module(module_name, pipe_name)
            pyarg = _get_pyarg(*args, steps=steps, context=context, **kwargs)
            _pykwargs = _gen_pykwargs(*args, steps=steps, context=context, **kwargs)
            pykwargs = dict(_pykwargs)
            step = (module_id, pipeline(pyarg, **pykwargs))

        steps.update([step])
        yield step


def _get_input_module(
    parsed_pipe_def: ParsedPipeDef,
    module_id: str,
    steps: Steps | None = None,
    **split_ids: int,
) -> Id | StepValue | None:
    source = None if steps is None else iter([{"forever": True}])

    if module_id in parsed_pipe_def["embed"]:
        source = "_INPUT"
    else:
        for wire in parsed_pipe_def["wires"].values():
            # if the wire is to this module and it's the default input and it's
            # the default output:
            if _is_default(wire, module_id, True):
                src_module_id = get_module_id(wire)

                if steps is None and src_module_id in split_ids:
                    pos = split_ids[src_module_id]
                    source = f"{src_module_id}_{pos}"
                elif steps is None:
                    source = src_module_id
                else:
                    source = steps[src_module_id]

                break

    return Id(source) if steps is None else source


def get_wire(
    src: str, tgt: str, wid: str, sid: str = "_OUTPUT", tid: str = "_INPUT"
) -> Wire:
    return Wire(
        {
            "id": wid,
            "src": {"id": sid, "moduleid": src},
            "tgt": {"id": tid, "moduleid": tgt},
        }
    )


def convert_dag(dag: PipeDag) -> PipeDef:
    """
    Expand a bare-bones DAG into a full JSON pipeline

    A DAG lists ``modules`` (``id``/``type``/opaque ``conf``) and, optionally,
    ``wires`` as ``[source_id, target_id]`` pairs. When ``wires`` is omitted or
    empty the modules are chained linearly in listing order. A module ``id`` is
    optional too and defaults to ``sw-{n}`` (1-based listing order), so the
    concise wireless form can drop ids entirely; supply ids when ``wires``
    reference them. The terminal ``output`` node and the verbose ``src``/``tgt``
    wire endpoints are generated automatically; every sink (a module that is
    never a wire source) is connected to ``_OUTPUT``.

    Note: every generated wire targets ``_INPUT``, so fan-in operators such as
    ``union``/``join`` (whose secondary inputs need ``_OTHER{n}`` targets in a
    full pipe definition) cannot be expressed by the ``[source, target]`` pair
    format and must be authored as a full pipe definition instead.
    """
    modules = enumerate(dag["modules"], 1)
    module_ids = [module.get("id", f"sw-{index}") for index, module in modules]
    linear = list(pairwise(module_ids))
    wires = [tuple(wire) for wire in dag.get("wires") or linear]
    sources = {src for src, _ in wires}
    output_edges = [(mid, "_OUTPUT") for mid in module_ids if mid not in sources]
    edges = [*wires, *output_edges]
    output = PipeModule(id="_OUTPUT", type="output", conf={})
    zipped = zip(dag["modules"], module_ids, strict=False)
    modules = [PipeModule({**module, "id": mid}) for module, mid in zipped] + [output]
    edge_pairs = enumerate(edges, 1)
    full_wires = [get_wire(src, tgt, f"_w{index}") for index, (src, tgt) in edge_pairs]
    return PipeDef({"modules": modules, "wires": full_wires})


def parse_pipe_def(pipe_def: PipeDef, pipe_name: str = "anonymous") -> ParsedPipeDef:
    """
    Parse pipe JSON into internal structures

    Parameters
    ----------
    pipe_def -- JSON representation of the pipe
    pipe_name -- a name for the pipe (used for linking pipes)

    Returns
    -------
    pipe -- an internal representation of a pipe

    """
    graph = defaultdict(list, gen_embed_graph(pipe_def))
    [graph[k].append(v) for k, v in gen_graph(pipe_def)]
    modules = {
        key: PipeModule({**module, "conf": _lower_keys(module["conf"])})
        for key, module in gen_modules(pipe_def)
    }
    embed = {
        key: PipeModule({**module, "conf": _lower_keys(module["conf"])})
        for key, module in gen_modules(pipe_def, embedded=True)
    }
    modules.update(embed)

    return {
        "name": pythonise(pipe_name),
        "modules": modules,
        "embed": embed,
        "graph": dict(gen_parented_graph(graph)),
        "wires": dict(gen_wires(pipe_def)),
    }


@overload
def _build_pipeline(  # noqa: E704
    *args: Any,
    is_async: Literal[True],
    **kwargs: Any,
) -> AsyncPipeParser | AsyncPipeItems: ...
@overload  # noqa: E302
def _build_pipeline(  # noqa: E704
    *args: Any,
    is_async: Literal[False] = ...,
    **kwargs: Any,
) -> SyncPipeParser | ParserOutput: ...
def _build_pipeline(  # noqa: E302
    parsed_pipe_def: ParsedPipeDef,
    module_names: Iterable[str],
    module_ids: Sequence[str],
    *,
    is_async: bool = False,
    context: Context | None = None,
    **kwargs: bool,
) -> StepValue:
    ntype = "async_pipe" if is_async else "pipe"
    pipe_names = gen_names(module_ids, parsed_pipe_def, ntype)
    _steps = _gen_steps(
        parsed_pipe_def,
        module_ids=module_ids,
        module_names=module_names,
        pipe_names=pipe_names,
        steps={},
        context=context,
        **kwargs,
    )
    steps = dict(_steps)
    _module_id = module_ids[-1]
    module_id = _module_id if isinstance(_module_id, str) else _module_id[-1]
    return steps[module_id]


def _get_descriptions(
    parsed_pipe_def: ParsedPipeDef,
    context: Context | None = None,
    mode: ExecutionMode | None = None,
    inputs: Inputs | None = None,
    **kwargs: bool,
) -> list[PipelineDescription] | list[str | tuple[str, ...]] | list[str]:
    context = context or Context(mode=mode, inputs=inputs, **kwargs)
    pydeps = extract_dependencies(parsed_pipe_def)
    pyinput = extract_input(parsed_pipe_def)

    if context.mode is ExecutionMode.DESCRIBE:
        pipeline = [PipelineDescription({"inputs": pyinput, "dependencies": pydeps})]
    elif context.mode is ExecutionMode.DESCRIBE_INPUTS:
        pipeline = pyinput
    elif context.mode is ExecutionMode.DESCRIBE_DEPENDENCIES:
        pipeline = pydeps
    else:
        pipeline = []

    return pipeline


def _resolve_leaf_modules(parsed_pipe_def: ParsedPipeDef) -> None:
    # Fail fast on unsupported leaf modules, including ones disconnected from the
    # graph that the lazy per-step build never reaches. The terminal ``output``
    # marker and `pipe`-prefixed sub-pipelines resolve via their own paths.
    for module in parsed_pipe_def["modules"].values():
        module_name = module["type"]

        if module_name != "output" and not module_name.startswith("pipe"):
            resolve_module(module_name, "pipe")


def build_pipeline(
    parsed_pipe_def: ParsedPipeDef,
    context: Context | None = None,
    mode: ExecutionMode | None = None,
    inputs: Inputs | None = None,
    **kwargs: bool,
) -> Stream:
    """
    Convert a pipe into an executable Python pipeline

    If describe_input or describe_dependencies then just
    return that instead of the pipeline
    """
    context = context or Context(mode=mode, inputs=inputs, **kwargs)
    module_ids = topological_sort(parsed_pipe_def["graph"])

    if context.mode is ExecutionMode.RUN:
        _resolve_leaf_modules(parsed_pipe_def)
        module_names = gen_names(module_ids, parsed_pipe_def)
        args = (parsed_pipe_def, module_names, module_ids)
        pipeline = _build_pipeline(*args, is_async=False, context=context, **kwargs)
    else:
        args = (parsed_pipe_def, context)
        pipeline = _get_descriptions(*args, mode=None, inputs=None, **kwargs)

    yield from pipeline


async def abuild_pipeline(
    parsed_pipe_def: ParsedPipeDef,
    context: Context | None = None,
    mode: ExecutionMode | None = None,
    inputs: Inputs | None = None,
    **kwargs: bool,
) -> AsyncStream:
    """
    Convert a pipe into an executable Python pipeline

    If describe_input or describe_dependencies then just
    return that instead of the pipeline
    """
    context = context or Context(mode=mode, inputs=inputs, **kwargs)
    module_ids = topological_sort(parsed_pipe_def["graph"])

    if context.mode is ExecutionMode.RUN:
        _resolve_leaf_modules(parsed_pipe_def)
        module_names = gen_names(module_ids, parsed_pipe_def)
        args = (parsed_pipe_def, module_names, module_ids)
        pipeline = await _build_pipeline(
            *args, is_async=True, context=context, **kwargs
        )
    else:
        args = (parsed_pipe_def, context)
        pipeline = _get_descriptions(*args, mode=None, inputs=None, **kwargs)

    for item in pipeline:
        yield item


def _ruff_format(code: str) -> str:
    kwargs = {"input": code, "capture_output": True, "text": True}

    try:
        result = subprocess.run(
            ["ruff", "format", "-"],  # noqa: S607
            check=True,
            **kwargs,
        )
    except (OSError, subprocess.CalledProcessError):
        formatted = code
    else:
        formatted = result.stdout or code

    return formatted


def stringify_pipe(
    parsed_pipe_def: ParsedPipeDef,
    context: Context | None = None,
    *,
    is_async: bool = False,
    mode: ExecutionMode | None = None,
    inputs: Inputs | None = None,
    **kwargs: bool,
) -> str:
    """Convert a pipe into Python script (async/anyio variant when ``is_async``)."""
    module_ids = topological_sort(parsed_pipe_def["graph"], strict=True)
    module_names = gen_names(module_ids, parsed_pipe_def)
    pipe_names = gen_names(module_ids, parsed_pipe_def, ntype="pipe")

    env = Environment(loader=PackageLoader("riko"), autoescape=False)  # noqa: S701
    template = env.get_template("pypipe_async.txt" if is_async else "pypipe.txt")
    _string_modules = _gen_string_modules(
        parsed_pipe_def,
        module_ids=module_ids,
        module_names=module_names,
        pipe_names=pipe_names,
        context=context,
        mode=mode,
        inputs=inputs,
        **kwargs,
    )

    string_modules = list(_string_modules)
    single_source_names = {m["name"] for m in string_modules if not m["is_collection"]}
    embed_names = set(_gen_embed_module_names(parsed_pipe_def)) - single_source_names
    keys = ["is_sub_pipe", "name", "pipe_name", "alias"]
    single_sources = {
        tuple(m[k] for k in keys) for m in string_modules if not m["is_collection"]
    }
    embeds = {(False, n, n, _module_alias(n)) for n in embed_names}
    subpipes = {(True, n, n, n) for n in _gen_embed_subpipe_names(parsed_pipe_def)}
    _uniq_modules = sorted(single_sources | embeds | subpipes)
    uniq_modules = [dict(zip(keys, m, strict=False)) for m in _uniq_modules]

    pyinput = extract_input(parsed_pipe_def)
    data = TemplateData(
        {
            "uniq_modules": [cast(AbbrevStringModule, m) for m in uniq_modules],
            "modules": string_modules,
            "pipe_name": parsed_pipe_def["name"],
            "inputs": pyinput,
            "dependencies": extract_dependencies(parsed_pipe_def),
            "embedded_pipes": parsed_pipe_def["embed"],
            "last_module": module_ids[-1],
            "raw_confs": sorted(_used_raw_confs(parsed_pipe_def)),
            "use_collection": any(m["is_collection"] for m in string_modules),
            "subtype": "source" if not pyinput else "transformer",
        }
    )

    return _ruff_format(template.render(**data))


def compile(
    pipe_def: PipeDef,
    pipe_name: str = "anonymous",
    context: Context | None = None,
    mode: ExecutionMode | None = None,
    inputs: Inputs | None = None,
    **kwargs: bool,
) -> str:
    """Compile a JSON pipe definition into a Python module"""
    parsed_pipe_def = parse_pipe_def(pipe_def, pipe_name)
    args = (parsed_pipe_def, context)
    return stringify_pipe(*args, mode=mode, inputs=inputs, **kwargs)
