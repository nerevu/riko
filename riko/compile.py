"""Compile/Translate Yahoo Pipe into Python

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
        pipe = parse_pipe_def(pipe_def, pipe_name)
        pipeline = build_pipeline(pipe)
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

from json import dumps, JSONEncoder
from codecs import open
from itertools import chain
from collections import defaultdict
from importlib import import_module
from pprint import PrettyPrinter

from jinja2 import Environment, PackageLoader

from riko import utils
from riko.pprint2 import Id, repr_args, str_args
from riko.topsort import topological_sort


class MyPrettyPrinter(PrettyPrinter):
    def format(self, object, maxlevels, level, **kwargs):
        if isinstance(object, unicode):
            return (object.encode("utf8"), True, False)
        else:
            return PrettyPrinter.format(self, object, maxlevels, level, **kwargs)


class CustomEncoder(JSONEncoder):
    def default(self, obj):
        if set(["quantize", "year", "tm_hour"]).intersection(dir(obj)):
            return str(obj)
        elif set(["next", "union"]).intersection(dir(obj)):
            return list(obj)

        return JSONEncoder.default(self, obj)


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
                data = unicode(MyPrettyPrinter().pformat(data), "utf-8")

            return f.write(data)


def _gen_string_modules(
    pipe, module_ids=None, module_names=None, pipe_names=None, **kwargs
):
    zipped = zip(module_ids, module_names, pipe_names)

    for module_id, module_name, pipe_name in zipped:
        pyarg = _get_pyarg(pipe, module_id, **kwargs)
        pykwargs = dict(_gen_pykwargs(pipe, module_id, **kwargs))

        if kwargs.get("verbose"):
            nconf_kwargs = filter(lambda x: x[0] != "conf", pykwargs.items())
            conf_kwargs = filter(lambda x: x[0] == "conf", pykwargs.items())
            all_args = chain([pyarg], nconf_kwargs, conf_kwargs)

            print("%s = %s(%s)" % (module_id, pipe_name, str_args(all_args)))

        yield {
            "args": repr_args(chain([pyarg], pykwargs.items())),
            "id": module_id,
            "sub_pipe": module_name.startswith("pipe_"),
            "name": module_name,
            "pipe_name": pipe_name,
        }


def _gen_steps(pipe, module_ids=None, module_names=None, pipe_names=None, **kwargs):
    zipped = zip(module_ids, module_names, pipe_names)

    for module_id, module_name, pipe_name in zipped:
        if module_name.startswith("pipe_"):
            # Import any required sub-pipelines and user inputs
            # Note: assumes they have already been compiled to accessible .py
            # files
            import_name = "riko.pypipelines.%s" % module_name
        else:
            import_name = "riko.modules.%s" % module_name

        module = import_module(import_name)
        pipe_generator = getattr(module, pipe_name)
        pyarg = _get_pyarg(pipe, module_id, **kwargs)
        pykwargs = dict(_gen_pykwargs(pipe, module_id, **kwargs))
        yield (module_id, pipe_generator(pyarg, **pykwargs))


def _get_pyarg(pipe, module_id, steps=None, **kwargs):
    describe = kwargs.get("describe_input") or kwargs.get("describe_dependencies")

    if not (describe and steps):
        # find the default input of this module
        input_module = _get_input_module(pipe, module_id, steps)
        return Id(input_module)


def _gen_pykwargs(pipe, module_id, steps=None, **kwargs):
    module = pipe["modules"][module_id]
    yield ("conf", module["conf"])

    describe = kwargs.get("describe_input") or kwargs.get("describe_dependencies")

    if not (describe and steps):
        # find the default input of this module
        for wire in pipe["wires"].values():
            moduleid = utils.pythonise(wire["src"]["moduleid"])

            # todo? this equates the outputs
            is_default_out_only = (
                utils.pythonise(wire["tgt"]["moduleid"]) == module_id
                and wire["tgt"]["id"] != "_INPUT"
                and wire["src"]["id"].startswith("_OUTPUT")
            )

            # if the wire is to this module and it's *NOT* the default input
            # but it *is* the default output
            if is_default_out_only:
                # set the extra inputs of this module as pykwargs of this module
                pipe_id = utils.pythonise(wire["tgt"]["id"])
                yield (pipe_id, steps[moduleid] if steps else Id(moduleid))

        # set splits in the pykwargs if this is split module
        filter_func = lambda v: module_id == utils.pythonise(v["src"]["moduleid"])

        if module["type"] == "split":
            filtered = filter(filter_func, pipe["wires"].values())
            count = len(list(filtered))
            updated = count if steps else Id(count)
            yield ("splits", updated)


def _get_input_module(pipe, module_id, steps):
    input_module = None

    for wire in pipe["wires"].values():
        moduleid = utils.pythonise(wire["src"]["moduleid"])

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


def parse_pipe_def(pipe_def, pipe_name="anonymous"):
    """Parse pipe JSON into internal structures

    Parameters
    ----------
    pipe_def -- JSON representation of the pipe
    pipe_name -- a name for the pipe (used for linking pipes)

    Returns:
    pipe -- an internal representation of a pipe
    """
    graph = defaultdict(list)
    [graph[k].append(v) for k, v in utils.gen_graph(pipe_def)]

    return {
        "name": utils.pythonise(pipe_name),
        "modules": dict(utils.gen_modules(pipe_def)),
        "graph": dict(utils.gen_parented_graph(graph)),
        "wires": dict(utils.gen_wires(pipe_def)),
    }


def build_pipeline(pipe, pipe_def, **kwargs):
    """Convert a pipe into an executable Python pipeline

    If describe_input or describe_dependencies then just
    return that instead of the pipeline
    """
    module_ids = topological_sort(pipe["graph"])
    pydeps = utils.extract_dependencies(pipe_def=pipe_def)
    pyinput = utils.extract_input(pipe_def=pipe_def)

    if kwargs.get("describe_input") and kwargs.get("describe_dependencies"):
        pipeline = [{"inputs": pyinput, "dependencies": pydeps}]
    elif kwargs.get("describe_input"):
        pipeline = pyinput
    elif kwargs.get("describe_dependencies"):
        pipeline = pydeps
    else:
        updates = {
            "module_ids": module_ids,
            "module_names": utils.gen_names(module_ids, pipe),
            "pipe_names": utils.gen_names(module_ids, pipe, "pipe"),
        }

        steps = dict(_gen_steps(pipe, **kwargs, **updates))
        pipeline = steps[module_ids[-1]]

    yield from pipeline


def stringify_pipe(pipe, pipe_def, **kwargs):
    """Convert a pipe into Python script"""
    module_ids = topological_sort(pipe["graph"])

    updates = {
        "module_ids": module_ids,
        "module_names": utils.gen_names(module_ids, pipe),
        "pipe_names": utils.gen_names(module_ids, pipe, "pipe"),
    }

    pydeps = utils.extract_dependencies(pipe_def=pipe_def)
    pyinput = utils.extract_input(pipe_def=pipe_def)
    env = Environment(loader=PackageLoader("riko"))
    template = env.get_template("pypipe.txt")
    modules = list(_gen_string_modules(pipe, **kwargs, **updates))
    keys = ["sub_pipe", "name", "pipe_name"]
    uniq_modules = set(tuple(m[k] for k in keys) for m in modules)

    data = {
        "uniq_modules": [dict(zip(keys, m)) for m in uniq_modules],
        "modules": modules,
        "pipe_name": pipe["name"],
        "inputs": pyinput,
        "dependencies": pydeps,
        "last_module": module_ids[-1],
    }

    return template.render(**data)
