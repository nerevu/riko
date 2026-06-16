"""
Compile/Translate Yahoo Pipe into Python

Takes a JSON representation of a Yahoo pipe and either:
a) translates it into a Python script containing a function
(using generators to build the pipeline) or
b) compiles it as a pipeline of generators which can be executed
in-process

Usage:
a) python riko/compile.py tests/pipelines/testpipe1.json
python riko/pypipelines/testpipe1.py

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

from codecs import open
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from importlib import import_module
from itertools import chain
from json import JSONEncoder, dumps
from pprint import PrettyPrinter

from jinja2 import Environment, PackageLoader

from riko import Context, utils
from riko.modules.forever import pipe as forever
from riko.pprint2 import Id, repr_args, str_args
from riko.topsort import topological_sort
from riko.types.compile import Wire
from riko.types.general import Items, ParsedPipeDef, PipeDef, Step, Steps, SyncPipeline


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
        print(f"{module_name=}")
        pyarg = _get_pyarg(parsed_pipe_def, module_id, **kwargs)
        pykwargs = dict(_gen_pykwargs(parsed_pipe_def, module_id, **kwargs))

        if context.verbose:
            # con_args = filter(lambda x: x != Id("context"), pyargs):
            nconf_kwargs = filter(lambda x: x[0] != "conf", pykwargs.items())
            conf_kwargs = filter(lambda x: x[0] == "conf", pykwargs.items())
            all_args = chain([pyarg], nconf_kwargs, conf_kwargs)
            print(f"{module_id} = {pipe_name}({str_args(all_args)})")

        yield {
            "args": repr_args(chain([pyarg], pykwargs.items())),
            "id": module_id,
            # "sub_pipe": module_name.startswith("pipe_"),
            "sub_pipe": module_id in parsed_pipe_def["embed"],
            "name": module_name,
            "pipe_name": pipe_name,
        }


def _get_pyarg(
    parsed_pipe_def: ParsedPipeDef,
    module_id: str,
    steps: Steps | None = None,
    context: Context | None = None,
    **kwargs,
):
    context = context or Context(**kwargs)
    describe = context.describe_input or context.describe_dependencies

    # find the default input of this module
    input_module = _get_input_module(parsed_pipe_def, module_id, steps)

    if describe and steps:
        print("You must not specify both describe and steps. Assuming steps.")

    return input_module if steps else Id(input_module)


def _gen_pykwargs(
    parsed_pipe_def: ParsedPipeDef,
    module_id: str,
    steps: Mapping | None = None,
    context: Context | None = None,
    **kwargs,
):
    module = parsed_pipe_def["modules"][module_id]
    yield ("conf", module["conf"])

    context = context or Context(**kwargs)
    yield ("context", context)

    describe = context.describe_input or context.describe_dependencies

    if describe and steps:
        print("You must not specify both describe and steps. Assuming steps.")

    # find the default input of this module
    for wire in parsed_pipe_def["wires"].values():
        module_id = get_module_id(wire)

        # todo? this equates the outputs
        is_default_out_only = (
            utils.pythonise(wire, key="tgt.moduleid") == module_id
            and wire["tgt"]["id"] != "_INPUT"
            and wire["src"]["id"].startswith("_OUTPUT")
        )

        # if the wire is to this module and it's *NOT* the default input
        # but it *is* the default output
        if is_default_out_only:
            # set the extra inputs of this module as pykwargs of this module
            pipe_id = utils.pythonise(wire, key="tgt.id")
            yield (pipe_id, steps[module_id] if steps else Id(module_id))

    if module["type"] == "loop":
        value = module["conf"]["embed"]["value"]
        pipe_id = utils.pythonise(value["id"])
        updated = steps[pipe_id] if steps else Id(f"pipe_{pipe_id}")
        yield ("embed", updated)

    if module["type"] == "split":
        filtered = [
            v
            for v in parsed_pipe_def["wires"].values()
            if module_id == get_module_id(v)
        ]
        count = len(filtered)
        updated = count if steps else Id(count)
        yield ("splits", updated)


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
        if module_name.startswith("pipe_"):
            import_name = f"riko.pypipelines.{module_name}"
        else:
            import_name = f"riko.modules.{module_name}"

        module = import_module(import_name)
        pipeline: SyncPipeline = getattr(module, pipe_name)

        if module_id in parsed_pipe_def["embed"]:
            # We need to wrap submodules (used by loops) so we can pass the
            # input at runtime (as we can to sub-pipelines)
            # Note: no embed (so no subloops) or wire pykwargs are passed
            pipeline.__name__ = str(f"pipe_{module_id}")
            step = (module_id, pipeline)
        else:  # else this module is not embedded:
            pyarg = _get_pyarg(parsed_pipe_def, module_id, **kwargs)
            pykwargs = dict(_gen_pykwargs(parsed_pipe_def, module_id, **kwargs))
            step = (module_id, pipeline(pyarg, **pykwargs))

        kwargs["steps"].update(step)
        yield step


def _get_input_module(
    parsed_pipe_def: ParsedPipeDef, module_id: str, steps: Steps | None = None
):
    input_module = steps.get("forever") if steps else None

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
                input_module = steps[moduleid] if steps else moduleid
                break

    return input_module


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
    modules = dict(utils.gen_modules(pipe_def))
    embed = dict(utils.gen_modules(pipe_def, embedded=True))
    modules.update(embed)

    return {
        "name": utils.pythonise(pipe_name),
        "modules": modules,
        "embed": embed,
        "graph": dict(utils.gen_parented_graph(graph)),
        "wires": dict(utils.gen_wires(pipe_def)),
    }


def build_pipeline(
    parsed_pipe_def: ParsedPipeDef,
    pipe_def: PipeDef,
    context: Context | None = None,
    **kwargs,
) -> Items:
    """
    Convert a pipe into an executable Python pipeline

    If describe_input or describe_dependencies then just
    return that instead of the pipeline
    """
    context = context or Context(**kwargs)

    module_ids = topological_sort(parsed_pipe_def["graph"])
    pydeps = utils.extract_dependencies(pipe_def=pipe_def)
    pyinput = utils.extract_input(pipe_def=pipe_def)

    if context.describe_input and context.describe_dependencies:
        pipeline = [{"inputs": pyinput, "dependencies": pydeps}]
    elif context.describe_input:
        pipeline = pyinput
    elif context.describe_dependencies:
        pipeline = pydeps
    else:
        updates = {
            "module_ids": module_ids,
            "module_names": utils.gen_names(module_ids, parsed_pipe_def),
            "pipe_names": utils.gen_names(module_ids, parsed_pipe_def, "pipe"),
            "steps": {"forever", forever()},
        }

        steps = dict(_gen_steps(parsed_pipe_def, **kwargs, **updates))
        _module_id = module_ids[-1]
        module_id = _module_id if isinstance(_module_id, str) else _module_id[-1]
        pipeline = steps[module_id]

    yield from pipeline


def stringify_pipe(parsed_pipe_def: ParsedPipeDef, pipe_def: PipeDef, **kwargs) -> str:
    """Convert a pipe into Python script"""
    module_ids = topological_sort(parsed_pipe_def["graph"])

    updates = {
        "module_ids": module_ids,
        "module_names": utils.gen_names(module_ids, parsed_pipe_def),
        "pipe_names": utils.gen_names(module_ids, parsed_pipe_def, ntype="pipe"),
    }

    env = Environment(loader=PackageLoader("riko"))
    template = env.get_template("pypipe.txt")
    modules = list(_gen_string_modules(parsed_pipe_def, **kwargs, **updates))
    keys = ["sub_pipe", "name", "pipe_name"]
    uniq_modules = {tuple(m[k] for k in keys) for m in modules}

    data = {
        "uniq_modules": [dict(zip(keys, m, strict=False)) for m in uniq_modules],
        "modules": modules,
        "pipe_name": parsed_pipe_def["name"],
        "inputs": utils.extract_input(pipe_def=pipe_def),
        "dependencies": utils.extract_dependencies(pipe_def=pipe_def),
        "embedded_pipes": parsed_pipe_def["embed"],
        "last_module": module_ids[-1],
    }

    return template.render(**data)
