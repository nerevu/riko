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
from collections.abc import Iterable, Iterator
from importlib import import_module
from itertools import pairwise
from json import JSONEncoder, dumps, loads
from pathlib import Path
from pprint import PrettyPrinter
from typing import Literal, cast, overload

from jinja2 import Environment, PackageLoader

from riko import Context, utils
from riko.context import ExecutionMode
from riko.exceptions import UnsupportedModuleError, UnsupportedPipelineError
from riko.pprint2 import Id, repr_arg
from riko.topsort import topological_sort
from riko.types.compile import ParsedPipeDef, PipeDag, PipeDef, PipeModule, Wire
from riko.types.general import (
    AsyncPipeParser,
    ParserOutput,
    Pipeline,
    Step,
    Steps,
    Stream,
    SyncPipeParser,
)
from riko.types.modules import (
    AnyModuleRawConf,
    ConfArg,
    Embed,
    LoopConf,
    LoopRawConf,
    Value,
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
    def format(self, object, *args, **kwargs):
        if isinstance(object, bytes):
            object = object.decode("utf8")

        return PrettyPrinter.format(self, object, *args, **kwargs)


class CustomEncoder(JSONEncoder):
    def default(self, o):
        if {"quantize", "year", "tm_hour"}.intersection(dir(o)):
            return str(o)
        elif {"next", "union"}.intersection(dir(o)):
            return list(o)

        return JSONEncoder.default(self, o)


def get_module_id(wire: Wire):
    return utils.pythonise(wire, key="src.moduleid")


def write_file(data, path, pretty=False):
    if data and path:
        with open(path, "w", encoding="utf-8") as f:
            if hasattr(data, "keys") and pretty:
                kwargs = {
                    "cls": CustomEncoder,
                    "sort_keys": True,
                    "indent": 4,
                    "ensure_ascii": False,
                }

                data = dumps(data, **kwargs)
            elif hasattr(data, "keys"):
                data = dumps(data, ensure_ascii=False)
            elif pretty:
                data = MyPrettyPrinter().pformat(data)

            return f.write(data)


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
    value = embed.get("value")
    embed_type = value.get("type")
    parts = []

    for key, val in value.items():
        rendered = _conf_source(embed_type, val) if key == "conf" else repr_arg(val)
        parts.append(f"{repr_arg(key)}: {rendered}")

    return f"{{'type': 'module', 'value': {{{', '.join(parts)}}}}}"


def _render_loop(conf: LoopConf) -> str:
    parts = []

    for key, val in conf.items():
        rendered = _render_embed(cast(Embed, val)) if key == "embed" else repr_arg(val)
        parts.append(f"{repr_arg(key)}: {rendered}")

    return f"{{{', '.join(parts)}}}"


def _conf_source(module_name: str, conf: object) -> str:
    raw = _RAW_CONFS.get(module_name)

    if module_name == "loop" and isinstance(conf, dict) and "embed" in conf:
        inner = _render_loop(cast(LoopConf, conf))
    else:
        inner = repr_arg(conf)

    return f"{raw}({inner})" if raw else inner


def _render_conf(module_name: str, conf: object) -> str:
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


def _used_raw_confs(parsed_pipe_def: ParsedPipeDef) -> set[str]:
    used = set()

    for module in parsed_pipe_def["modules"].values():
        conf = module["conf"] or {}

        if _collection_sources(conf) is not None:
            continue

        if raw := _RAW_CONFS.get(module["type"]):
            used.add(raw)

        if (
            (embed := cast(LoopRawConf, conf).get("embed"))
            and (embed_type := embed.get("value", {}).get("type"))
            and (embed_raw := _RAW_CONFS.get(embed_type))
        ):
            used.add(embed_raw)

    return used


def _collection_sources(
    conf: AnyModuleRawConf | None,
) -> list[dict[str, object]] | None:
    if conf and (url := conf.get("url")) and isinstance(url, list):
        urls = cast(list[Value], url)
        return [{"url": url["value"]} for url in urls]


def _render_args(
    module_name: str, pyarg: object, pykwargs: Iterable[tuple[str, object]]
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
    **kwargs,
):
    zipped = zip(module_ids, module_names, pipe_names, strict=False)
    context = context or Context(**kwargs)

    for module_id, module_name, pipe_name in zipped:
        if module_id in parsed_pipe_def["embed"]:
            continue

        args = (parsed_pipe_def, module_id)
        sub_pipe = module_name.startswith("pipe")
        pyarg = _get_pyarg(*args, steps=None, **kwargs)
        conf = parsed_pipe_def["modules"][module_id]["conf"]
        sources = _collection_sources(conf)

        if collection := sources is not None:
            expr = f"SyncCollection({repr_arg(sources)}, context=context)"
        elif module_name == "output":
            expr = repr_arg(pyarg)
        elif sub_pipe:
            pykwargs = list(_gen_pykwargs(*args, steps=None, **kwargs))
            expr = f"{pipe_name}({_render_args(module_name, None, pykwargs)})"
        else:
            pykwargs = list(_gen_pykwargs(*args, steps=None, **kwargs))
            alias = _module_alias(module_name)
            expr = f"{alias}({_render_args(module_name, pyarg, pykwargs)})"

        yield {
            "id": module_id,
            "expr": expr,
            "alias": _module_alias(module_name),
            "sub_pipe": sub_pipe,
            "collection": collection,
            "name": module_name,
            "pipe_name": pipe_name,
        }


@overload  # noqa: E302
def _get_pyarg(  # noqa: E704
    parsed_pipe_def: ParsedPipeDef, module_id: str, steps: None = ..., **kwargs
) -> Id: ...
@overload  # noqa: E302
def _get_pyarg(  # noqa: E704
    parsed_pipe_def: ParsedPipeDef, module_id: str, steps: Steps, **kwargs
) -> ParserOutput | SyncPipeParser: ...
def _get_pyarg(  # noqa: E302
    parsed_pipe_def: ParsedPipeDef,
    module_id: str,
    steps: Steps | None = None,
    context: Context | None = None,
    **kwargs,
) -> ParserOutput | SyncPipeParser | Id:
    context = context or Context(**kwargs)
    describe = context.mode is not ExecutionMode.RUN

    # find the default input of this module
    input_module = _get_input_module(parsed_pipe_def, module_id, steps)

    if describe and steps:
        print("You must not specify both describe and steps. Assuming steps.")

    return input_module if steps is not None else Id(input_module)


@overload  # noqa: E302
def _gen_pykwargs(  # noqa: E704
    parsed_pipe_def: ParsedPipeDef, module_id: str, steps: None = ..., **kwargs
) -> Iterator[tuple[str, Id | Context | AnyModuleRawConf]]: ...
@overload  # noqa: E302
def _gen_pykwargs(  # noqa: E704
    parsed_pipe_def: ParsedPipeDef, module_id: str, steps: Steps, **kwargs
) -> Iterator[
    tuple[str, ParserOutput | SyncPipeParser | Context | AnyModuleRawConf]
]: ...
def _gen_pykwargs(  # noqa: E302
    parsed_pipe_def: ParsedPipeDef,
    module_id: str,
    steps: Steps | None = None,
    context: Context | None = None,
    **kwargs,
) -> Iterator[
    tuple[str, ParserOutput | SyncPipeParser | Id | Context | AnyModuleRawConf]
]:
    module = parsed_pipe_def["modules"][module_id]
    conf = module["conf"]
    keys = ("emit", "assign")

    if any(key in conf for key in keys):
        yield ("conf", {k: v for k, v in conf.items() if k not in keys})

        for key in keys:
            if key in conf:
                setting = cast(ConfArg, conf[key])
                yield (key, setting["value"])
    else:
        yield ("conf", conf)

    context = context or Context(**kwargs)
    yield ("context", context)

    describe = context.mode is not ExecutionMode.RUN

    if describe and steps:
        print("You must not specify both describe and steps. Assuming steps.")

    tgt_module_id = module_id
    others = []

    # find the default input of this module
    for wire in parsed_pipe_def["wires"].values():
        # todo? this equates the outputs
        is_default_out_only = (
            utils.pythonise(wire, key="tgt.moduleid") == tgt_module_id
            and wire["tgt"]["id"] != "_INPUT"
            and wire["src"]["id"].startswith("_OUTPUT")
        )

        # if the wire is to this module and it's *NOT* the default input
        # but it *is* the default output
        if is_default_out_only:
            # set the extra inputs of this module as pykwargs of this module
            src_module_id = get_module_id(wire)
            pipe_id = utils.pythonise(wire, key="tgt.id")
            source = steps[src_module_id] if steps is not None else Id(src_module_id)

            if pipe_id.startswith("_OTHER"):
                others.append(source)
            else:
                yield (pipe_id, source)

    if others:
        yield ("OTHERS", others)

    if module["type"] == "loop":
        value = cast(LoopRawConf, module["conf"])["embed"]["value"]
        pipe_id = utils.pythonise(value["id"])
        updated = Id(_module_alias(value["type"])) if steps is None else steps[pipe_id]
        yield ("embed", updated)

    if module["type"] == "split":
        wires = parsed_pipe_def["wires"].values()
        filtered = [v for v in wires if module_id == get_module_id(v)]
        count = len(filtered)
        updated = count if steps is not None else Id(count)
        yield ("splits", updated)


@overload
def _resolve_module(  # noqa: E704
    module_name: str,
    pipe_name: Literal["pipe"],
    compile_missing: Literal[False] = ...,
    file_path: Path | None = ...,
) -> SyncPipeParser: ...
@overload  # noqa: E302
def _resolve_module(  # noqa: E704
    module_name: str,
    pipe_name: Literal["async_pipe"],
    compile_missing: Literal[False] = ...,
    file_path: Path | None = ...,
) -> AsyncPipeParser: ...
@overload  # noqa: E302
def _resolve_module(  # noqa: E704
    module_name: str,
    pipe_name: str,
    compile_missing: Literal[False] = ...,
    file_path: Path | None = ...,
) -> Pipeline: ...
@overload  # noqa: E302
def _resolve_module(  # noqa: E704
    module_name: str,
    pipe_name: str,
    compile_missing: Literal[True],
    file_path: Path | None = ...,
) -> tuple[Pipeline | None, ParsedPipeDef | None]: ...
def _resolve_module(  # noqa: E302
    module_name: str,
    pipe_name: str,
    compile_missing=False,
    file_path: Path | None = None,
) -> Pipeline | None | tuple[Pipeline | None, ParsedPipeDef | None]:
    module = parsed_pipe_def = None

    if module_name == "output":
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
    return (pipeline, parsed_pipe_def) if compile_missing else pipeline


def _gen_steps(
    parsed_pipe_def: ParsedPipeDef,
    *,
    module_ids: Iterable[str],
    module_names: Iterable[str],
    pipe_names: Iterable[str],
    **kwargs,
) -> Iterator[Step]:
    zipped = zip(module_ids, module_names, pipe_names, strict=False)
    kwargs.setdefault("steps", {})

    for module_id, module_name, pipe_name in zipped:
        pipeline = _resolve_module(module_name, pipe_name)

        if module_name == "output":
            # Legacy Yahoo Pipes. Its result is just its input stream.
            pyarg = _get_pyarg(parsed_pipe_def, module_id, **kwargs)
            step = (module_id, pyarg)
        elif module_id in parsed_pipe_def["embed"]:
            # We need to wrap submodules (used by loops) so we can pass the
            # input at runtime (as we can to sub-pipelines)
            # Note: no embed (so no subloops) or wire pykwargs are passed
            pipeline.__name__ = str(f"pipe_{module_id}")
            step = (module_id, pipeline)
        else:  # else this module is not embedded:
            pyarg = _get_pyarg(parsed_pipe_def, module_id, **kwargs)
            pykwargs = dict(_gen_pykwargs(parsed_pipe_def, module_id, **kwargs))
            step = (module_id, pipeline(pyarg, **pykwargs))

        kwargs["steps"].update([step])
        yield step


def _get_input_module(
    parsed_pipe_def: ParsedPipeDef, module_id: str, steps: Steps | None = None
):
    input_module = iter([{"forever": True}]) if steps is not None else None

    if module_id in parsed_pipe_def["embed"]:
        input_module = "_INPUT"
    else:
        for wire in parsed_pipe_def["wires"].values():
            moduleid = get_module_id(wire)

            # todo? this equates the outputs
            is_default_in_and_out = (
                utils.pythonise(wire["tgt"]["moduleid"]) == module_id
                and wire["tgt"]["id"] == "_INPUT"
                and wire["src"]["id"].startswith("_OUTPUT")
            )

            # if the wire is to this module and it's the default input and it's
            # the default output:
            if is_default_in_and_out:
                input_module = steps[moduleid] if steps is not None else moduleid
                break

    return input_module


def _wire(src: str, tgt: str, wid: str, sid="_OUTPUT", tid="_INPUT") -> Wire:
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
    full_wires = [_wire(src, tgt, f"_w{index}") for index, (src, tgt) in edge_pairs]
    return PipeDef({"modules": modules, "wires": full_wires})


def parse_pipe_def(pipe_def: PipeDef, pipe_name="anonymous") -> ParsedPipeDef:
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
    graph = defaultdict(list, utils.gen_embed_graph(pipe_def))
    [graph[k].append(v) for k, v in utils.gen_graph(pipe_def)]
    modules = {
        key: PipeModule({**module, "conf": _lower_keys(module["conf"])})
        for key, module in utils.gen_modules(pipe_def)
    }
    embed = {
        key: PipeModule({**module, "conf": _lower_keys(module["conf"])})
        for key, module in utils.gen_modules(pipe_def, embedded=True)
    }
    modules.update(embed)

    return {
        "name": utils.pythonise(pipe_name),
        "modules": modules,
        "embed": embed,
        "graph": dict(utils.gen_parented_graph(graph)),
        "wires": dict(utils.gen_wires(pipe_def)),
    }


def build_pipeline(
    parsed_pipe_def: ParsedPipeDef, context: Context | None = None, **kwargs
) -> Stream:
    """
    Convert a pipe into an executable Python pipeline

    If describe_input or describe_dependencies then just
    return that instead of the pipeline
    """
    context = context or Context(**kwargs)
    module_ids = topological_sort(parsed_pipe_def["graph"])
    pydeps = utils.extract_dependencies(parsed_pipe_def)
    pyinput = utils.extract_input(parsed_pipe_def)

    if context.mode is ExecutionMode.DESCRIBE:
        pipeline = [{"inputs": pyinput, "dependencies": pydeps}]
    elif context.mode is ExecutionMode.DESCRIBE_INPUTS:
        pipeline = pyinput
    elif context.mode is ExecutionMode.DESCRIBE_DEPENDENCIES:
        pipeline = pydeps
    else:
        updates = {
            "module_ids": module_ids,
            "module_names": utils.gen_names(module_ids, parsed_pipe_def),
            "pipe_names": utils.gen_names(module_ids, parsed_pipe_def, "pipe"),
            "steps": {},
            "context": context,
        }

        steps = dict(_gen_steps(parsed_pipe_def, **kwargs, **updates))
        _module_id = module_ids[-1]
        module_id = _module_id if isinstance(_module_id, str) else _module_id[-1]
        pipeline = steps[module_id]

    yield from pipeline


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


def stringify_pipe(parsed_pipe_def: ParsedPipeDef, **kwargs) -> str:
    """Convert a pipe into Python script"""
    module_ids = topological_sort(parsed_pipe_def["graph"])

    updates = {
        "module_ids": module_ids,
        "module_names": utils.gen_names(module_ids, parsed_pipe_def),
        "pipe_names": utils.gen_names(module_ids, parsed_pipe_def, ntype="pipe"),
    }

    env = Environment(loader=PackageLoader("riko"), autoescape=False)  # noqa: S701
    template = env.get_template("pypipe.txt")
    modules = list(_gen_string_modules(parsed_pipe_def, **kwargs, **updates))
    keys = ["sub_pipe", "name", "pipe_name", "alias"]
    top_names = {m["name"] for m in modules if not m["collection"]}
    module_tuples = {tuple(m[k] for k in keys) for m in modules if not m["collection"]}
    embed_names = set(_gen_embed_module_names(parsed_pipe_def)) - top_names
    embed_tuples = {(False, n, n, _module_alias(n)) for n in embed_names}
    uniq_modules = sorted(module_tuples | embed_tuples)

    data = {
        "uniq_modules": [dict(zip(keys, m, strict=False)) for m in uniq_modules],
        "modules": modules,
        "pipe_name": parsed_pipe_def["name"],
        "inputs": utils.extract_input(parsed_pipe_def),
        "dependencies": utils.extract_dependencies(parsed_pipe_def),
        "embedded_pipes": parsed_pipe_def["embed"],
        "last_module": module_ids[-1],
        "raw_confs": sorted(_used_raw_confs(parsed_pipe_def)),
        "use_collection": any(m["collection"] for m in modules),
    }

    return _ruff_format(template.render(**data))


def compile(pipe_def: PipeDef, pipe_name: str = "anonymous", **kwargs) -> str:
    """Compile a JSON pipe definition into a Python module"""
    parsed_pipe_def = parse_pipe_def(pipe_def, pipe_name)
    return stringify_pipe(parsed_pipe_def, **kwargs)
