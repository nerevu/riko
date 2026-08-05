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

Instead of passing a filename, a pipe id can be passed (-p) to fetch the
JSON from Yahoo, e.g.

python compile.py -p 2de0e4517ed76082dcddf66f7b218057

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
from collections.abc import Iterable, Iterator, Sequence
from datetime import date
from decimal import Decimal
from importlib import import_module
from itertools import pairwise
from json import JSONEncoder, dumps, loads
from pathlib import Path
from pprint import PrettyPrinter
from time import struct_time
from typing import Any, Literal, cast, overload

from jinja2 import Environment, PackageLoader

from riko import Context
from riko.context import ExecutionMode
from riko.dotdict import DotDict
from riko.exceptions import UnsupportedModuleError, UnsupportedPipelineError
from riko.modules._subpipe import is_subpipe, mark_subpipe
from riko.pprint2 import Id, repr_arg, repr_args
from riko.topsort import topological_sort
from riko.types.compile import (
    AbbrevStringModule,
    CanonicalOptions,
    EmbedRef,
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
    AsyncPipeParser,
    AsyncStream,
    ParserOutput,
    Pipeline,
    SplitOutputs,
    Step,
    Steps,
    StepValue,
    Stream,
    SyncPipeParser,
)
from riko.types.modules import (
    AnyModuleRawConf,
    ConfArg,
    CountArg,
    CountValues,
    Embed,
    LoopRawConf,
    ModuleName,
    Value,
)
from riko.types.values import Inputs
from riko.utils import (
    extract_dependencies,
    extract_input,
    gen_embed_graph,
    gen_graph,
    gen_modules,
    gen_names,
    gen_parented_graph,
    gen_wires,
    listize,
    pythonise,
)

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


def get_module_id(wire: Wire, stem: str = "src", base: str = "moduleid") -> str:
    return pythonise(wire, key=f"{stem}.{base}")


def write_file(data: object, path: str | None, pretty: bool = False) -> int | None:
    if data and path:
        with open(path, "w", encoding="utf-8") as f:
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


def _render_embed(embed: Embed) -> str:
    value = embed["value"]
    embed_type = value["type"]
    parts = []

    for key, val in value.items():
        if key == "conf":
            rendered = _conf_source(embed_type, cast(AnyModuleRawConf, val))
        else:
            rendered = repr_arg(cast(str | ModuleName | ConfArg, val))

        parts.append(f"{repr_arg(key)}: {rendered}")

    return f"{{'type': 'module', 'value': {{{', '.join(parts)}}}}}"


def _render_loop(conf: LoopRawConf) -> str:
    parts = []

    for key, val in conf.items():
        if key == "embed":
            rendered = _render_embed(cast(Embed, val))
        else:
            rendered = repr_arg(cast(Value, val))

        parts.append(f"{repr_arg(key)}: {rendered}")

    return f"{{{', '.join(parts)}}}"


def _conf_source(module_name: str, conf: AnyModuleRawConf | Id | Context) -> str:
    raw = _RAW_CONFS.get(module_name)

    if module_name == "loop" and isinstance(conf, dict) and "embed" in conf:
        inner = _render_loop(conf)
    else:
        inner = repr_arg(conf)

    return f"{raw}({inner})" if raw else inner


def _render_conf(module_name: str, conf: AnyModuleRawConf | Id | Context) -> str:
    return _conf_source(module_name, _lower_keys(conf))


def _gen_embed_module_names(parsed_pipe_def: ParsedPipeDef) -> Iterator[str]:
    for module in parsed_pipe_def["modules"].values():
        if (
            (conf := module["conf"])
            and (embed := cast(LoopRawConf, conf).get("embed"))
            and (embed_type := embed.get("value", {}).get("type"))
            and not embed_type.startswith("pipe")
        ):
            yield embed_type


def _split_port_index(port_id: str) -> int:
    if port_id == "_OUTPUT":
        return 0

    if port_id.startswith("_OUTPUT"):
        suffix = port_id.removeprefix("_OUTPUT")

        if suffix.isdigit() and int(suffix) >= 2:
            return int(suffix) - 1

    raise UnsupportedPipelineError(f"Invalid split output port: {port_id}")


def _resolve_wire_source(
    parsed_pipe_def: ParsedPipeDef,
    wire: Wire,
    steps: Steps | None,
) -> "Id | StepValue":
    src_module_id = get_module_id(wire)
    src_port = wire["src"]["id"]
    module = parsed_pipe_def["modules"].get(src_module_id)
    is_split = module is not None and module["type"] == "split"

    if is_split:
        index = _split_port_index(src_port)

        if steps is None:
            return Id(f"iter({src_module_id}_{index})")

        split_outputs = steps[src_module_id]
        return iter(cast("SplitOutputs", split_outputs)[index])

    if steps is None:
        return Id(src_module_id)

    return steps[src_module_id]


def _effective_split_count(
    parsed_pipe_def: ParsedPipeDef,
    module_id: str,
    conf: AnyModuleRawConf | None,
) -> int:
    port_indexes = []

    for wire in parsed_pipe_def["wires"].values():
        if get_module_id(wire) == module_id:
            src_port = wire["src"]["id"]

            if src_port.startswith("_OUTPUT"):
                port_indexes.append(_split_port_index(src_port))

    required = max(port_indexes, default=0) + 1
    conf_splits = DotDict(conf or {}).get("splits")
    has_explicit = conf_splits is not None
    configured = int(conf_splits) if has_explicit else 2

    if has_explicit and configured < required:
        raise UnsupportedPipelineError(
            f"split {module_id!r} defines {configured} outputs "
            f"but the graph references output {required}"
        )

    return max(configured, required)


def _effective_split_conf(
    parsed_pipe_def: ParsedPipeDef,
    module_id: str,
    conf: AnyModuleRawConf | None,
) -> AnyModuleRawConf | None:
    count = _effective_split_count(parsed_pipe_def, module_id, conf)
    conf_splits = DotDict(conf or {}).get("splits")

    if conf_splits is None and count > 2:
        injected: AnyModuleRawConf = {**(conf or {}), "splits": {"type": "int", "value": count}}
        return injected

    return conf


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

        if raw := _RAW_CONFS.get(module["type"]):
            used.add(raw)

        if (
            (embed := cast(LoopRawConf, conf or {}).get("embed"))
            and (embed_type := embed.get("value", {}).get("type"))
            and (embed_raw := _RAW_CONFS.get(embed_type))
        ):
            used.add(embed_raw)

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
    checked = False

    for module_id, module_name, pipe_name in zipped:
        if module_id in parsed_pipe_def["embed"]:
            continue

        args = (parsed_pipe_def, module_id)
        is_sub_pipe = module_name.startswith("pipe")
        pyarg = _get_pyarg(*args, steps=None, **kwargs)

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
            pykwargs = list(_gen_pykwargs(*args, steps=None, **kwargs))
            alias = _module_alias(module_name)
            expr = f"{alias}({_render_args(module_name, pyarg, pykwargs)})"

        if module_name == "split":
            splits = _effective_split_count(parsed_pipe_def, module_id, conf)
            eff_conf = _effective_split_conf(parsed_pipe_def, module_id, conf)

            if eff_conf is not conf:
                pykwargs = [
                    ("conf", eff_conf) if k == "conf" else (k, v)
                    for k, v in pykwargs
                ]
                alias = _module_alias(module_name)
                expr = f"{alias}({_render_args(module_name, pyarg, pykwargs)})"
        else:
            splits = 0

        yield StringModule(
            {
                "id": module_id,
                "expr": expr,
                "alias": _module_alias(module_name),
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
    steps: Steps | None = None,
    context: Context | None = None,
    mode: ExecutionMode | None = None,
    inputs: Inputs | None = None,
    **kwargs: bool,
) -> StepValue | Id | None:
    context = context or Context(mode=mode, inputs=inputs, **kwargs)

    if steps and context.mode is not ExecutionMode.RUN:
        print("You must not specify both describe and steps. Assuming steps.")

    return _get_input_module(parsed_pipe_def, module_id, steps)


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
            source = _resolve_wire_source(parsed_pipe_def, wire, steps)
            pipe_id = get_module_id(wire, stem="tgt", base="id")

            if pipe_id.startswith("_OTHER"):
                others.append(source)
            else:
                yield (pipe_id, source)

    if others:
        yield ("others", others)

    if module["type"] == "loop":
        embedded_module = cast(LoopRawConf, module["conf"])["embed"]["value"]
        pipe_id = pythonise(embedded_module["id"])
        updated = (
            Id(_module_alias(embedded_module["type"]))
            if steps is None
            else steps[pipe_id]
        )
        yield ("embed", updated)


@overload
def resolve_module(  # noqa: E704  # pyright: ignore[reportOverlappingOverload]
    module_name: Literal["output"],
    pipe_name: str,
    compile_missing: Literal[False] = ...,
    file_path: Path | None = ...,
) -> None: ...
@overload  # noqa: E302
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
    module = parsed_pipe_def = None

    if module_name == "output":
        # output is a virtual pipe, legacy from Yahoo Pipes; there's no real
        # module — the compiler just makes it return its input stream.
        pass
    elif module_name.startswith("pipe_"):
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
        try:
            module = import_module(f"riko.modules.{module_name}")
        except ModuleNotFoundError as e:
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
        pipeline = resolve_module(module_name, pipe_name)
        args = (parsed_pipe_def, module_id)

        if module_name == "output":
            # Legacy Yahoo Pipes. Its result is just its input stream.
            pyarg = _get_pyarg(*args, steps=steps, context=context, **kwargs)
            step = (module_id, pyarg)
        elif module_id in parsed_pipe_def["embed"]:
            # We need to wrap submodules (used by loops) so we can pass the
            # input at runtime (as we can to sub-pipelines)
            # Note: no embed (so no subloops) or wire pykwargs are passed
            pipeline.__name__ = str(f"pipe_{module_id}")
            step = (module_id, pipeline)
        else:  # else this module is not embedded:
            pyarg = _get_pyarg(*args, steps=steps, context=context, **kwargs)
            _args = (parsed_pipe_def, module_id)
            _pykwargs = _gen_pykwargs(*_args, steps=steps, context=context, **kwargs)
            pykwargs = dict(_pykwargs)

            if module_name == "split":
                orig_conf = parsed_pipe_def["modules"][module_id]["conf"]
                eff_conf = _effective_split_conf(parsed_pipe_def, module_id, orig_conf)
                pykwargs["conf"] = eff_conf
                result = tuple(list(stream) for stream in pipeline(pyarg, **pykwargs))
            else:
                result = pipeline(pyarg, **pykwargs)

            step = (module_id, result)

        steps.update([step])
        yield step


def _get_input_module(
    parsed_pipe_def: ParsedPipeDef,
    module_id: str,
    steps: Steps | None = None,
) -> Id | StepValue | None:
    source = None

    if module_id in parsed_pipe_def["embed"]:
        source = "_INPUT"
    else:
        for wire in parsed_pipe_def["wires"].values():
            # if the wire is to this module and it's the default input and it's
            # the default output:
            if _is_default(wire, module_id, True):
                resolved = _resolve_wire_source(parsed_pipe_def, wire, steps)
                source = resolved
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


@overload
def _arg_value(arg: None) -> None: ...  # noqa: E704
@overload
def _arg_value(arg: CountArg) -> str: ...  # noqa: E704
@overload
def _arg_value(arg: ConfArg) -> int | str | bool: ...  # noqa: E704
@overload
def _arg_value[T](arg: T) -> T: ...  # noqa: E704
def _arg_value[T](  # noqa: E302
    arg: ConfArg | CountArg | T | None,
) -> T | int | str | bool | None:
    return arg.get("value") if isinstance(arg, dict) else arg


def _canonical_options(module: PipeModule) -> CanonicalOptions:
    conf = cast(LoopRawConf, module["conf"])
    embedded_module = conf["embed"]["value"]
    opts = cast(CanonicalOptions, {})

    for key in ("field", "assign", "emit"):
        if (value := cast(str | None, module.get(key))) is None:
            value = cast(ConfArg | None, embedded_module.get(key))

        opts[key] = None if value is None else _arg_value(value)

    opts["count"] = _arg_value(conf.get("count"))
    return opts


def legacy_loop_to_canonical(module: PipeModule) -> PipeModule | LoopModule:
    opts = _canonical_options(module)
    conf = cast(LoopRawConf, module["conf"])
    embedded_module = conf["embed"]["value"]
    module_name = embedded_module["type"]
    embed_conf = embedded_module["conf"]

    # A pipe embed always stays a loop. A processor embed collapses to a direct
    # node only when its own fold matches the loop's per-parent fold — i.e. it
    # emits results or keeps just the first. With assign + count!="first" the
    # processor list-wraps into one item while the loop yields one copy per
    # result, so that case must stay a loop embedding the processor.
    emit_false = opts["emit"] is False
    keeps_many = opts["count"] != "first"
    is_loop = module_name.startswith("pipe") or (emit_false and keeps_many)
    _type = "loop" if is_loop else module_name
    result = PipeModule({"id": module["id"], "type": _type, "conf": embed_conf})

    if is_loop:
        result["embed"] = EmbedRef({"id": embedded_module["id"], "type": module_name})

    for k, v in opts.items():
        if v is not None:
            result[k] = v

    return cast(LoopModule, result) if is_loop else result


def normalize_raw_module(module: PipeModule) -> PipeModule | LoopModule:
    """
    Lift a legacy nested loop (``conf.embed.value``) to the canonical form the
    compiler consumes. ``_legacy_loop_to_canonical`` collapses a processor loop
    whose fold matches the loop (``emit`` mode or ``count="first"``) into a
    **direct processor node** (``count``/``field``/``assign``/``emit`` hoisted,
    embed conf flattened up, loop id kept). Ordinary modules pass through.

    The compact-loop cases (any ``pipe:<id>`` embed, or ``count=all``+``assign``)
    are **left legacy for now** — the compiler still reads the top-level ``embed``
    ref from `conf.embed.value`, so lifting them to a compact node waits on that
    consumption step. See docs/gameplans/loop-restructure.md.
    """
    result = module

    if module["type"] == "loop" and "embed" in module["conf"]:
        canonical = legacy_loop_to_canonical(module)

        if canonical.get("type") != "loop":
            result = canonical

    return result


def normalize_pipe_def(pipe_def: PipeDef) -> PipeDef:
    modules = [normalize_raw_module(m) for m in listize(pipe_def["modules"])]
    return cast(PipeDef, {**pipe_def, "modules": modules})


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
    pipe_def = normalize_pipe_def(pipe_def)
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
    # output graph that the lazy per-step build never reaches. `output` and
    # `pipe`-prefixed sub-pipelines resolve via their own paths.
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
    _uniq_modules = sorted(single_sources | embeds)
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
