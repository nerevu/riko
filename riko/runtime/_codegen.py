# vim: sw=4:ts=4:expandtab
"""
Generates a workflow module (``WorkflowModule``) from a ``Workflow``.

The generated ``WorkflowModule`` is Python source that rebuilds the workflow from
typed configuration classes. The ``WorkflowModule`` also exposes a ``pipe``/
``async_pipe`` callable that runs the workflow through the standard execution.

It is a readable, type-checkable rendering of the ``Workflow`` graph that can be edited
and imported like any Python source. Once saved as ``pipe_<id>.py`` in a package
registered as a workflow store, it can also be embedded in a ``loop`` by its name.


Examples:

    Basic usage::

        >>> from riko.runtime._pipeline import Pipeline
        >>> from riko.runtime._codegen import compile_workflow
        >>>
        >>> attrs = {"key": "title", "value": "riko"}
        >>> itembuilder = Pipeline.from_module("itembuilder", conf={"attrs": attrs})
        >>> pipeline = itembuilder.rename(conf={"rule": [{"field": "title"}]})
        >>> source = compile_workflow(pipeline.workflow, "pipe_demo")
        >>> print(next(l for l in source.splitlines() if l.startswith("pipe")))
        pipe = build_workflow_pipes(
        >>> print(next(l for l in source.splitlines() if l.startswith("DEPEND")))
        DEPENDENCIES: list[str] = ["itembuilder", "rename"]

"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jinja2 import Environment, PackageLoader

from riko.base._source_format import ruff_format
from riko.base._strutils import pythonise
from riko.definitions._workflow import normalize_workflow
from riko.types._guards import is_mapping
from riko.types._workflow import WorkflowModule

if TYPE_CHECKING:
    from collections.abc import Mapping

    from riko.definitions._nodes import ModuleNode
    from riko.definitions._workflow import WorkflowLike
    from riko.types._collections import FrozenConf
    from riko.types._compiler import Embed
    from riko.types._workflow import Edge, Endpoint
    from riko.types.modules import Conf

RAW_CONFS = {
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


def render_value(value: object) -> str:
    """Renders a JSON-native value as the Python literal that reproduces it."""
    if is_mapping(value):
        pairs = (f"{key!r}: {render_value(item)}" for key, item in value.items())
        result = "{" + ", ".join(pairs) + "}"
    elif isinstance(value, (list, tuple)):
        result = "[" + ", ".join(render_value(item) for item in value) + "]"
    else:
        result = repr(value)

    return result


def _resolve_raw_conf(name: str, conf: FrozenConf | Conf) -> str | None:
    """Supplies the raw config class a non-empty configuration is typed by, if any."""
    return RAW_CONFS.get(name) if len(conf) else None


def _render_conf(name: str, conf: FrozenConf | Conf) -> str:
    """Renders a module configuration, typed by its module's raw config class."""
    inner = render_value(conf)
    raw = _resolve_raw_conf(name, conf)
    return inner if raw is None else f"{raw}({inner})"


def _render_embed(embed: Embed) -> str:
    """Renders a loop's embedded module as the typed ``Embed`` that rebuilds it."""
    name = embed["name"]
    parts = [f"'name': {name!r}"]

    if (embed_id := embed.get("id")) is not None:
        parts.append(f"'id': {embed_id!r}")

    parts.append(f"'conf': {_render_conf(name, embed['conf'])}")
    return "Embed({" + ", ".join(parts) + "})"


def _render_node(node: ModuleNode) -> str:
    """Renders one node as the ``ModuleNode(...)`` entry that rebuilds it."""
    parts = [f"id={node.id!r}", f"name={node.name!r}"]

    if len(node.conf):
        parts.append(f"conf={_render_conf(node.name, node.conf)}")

    if node.embed is not None:
        parts.append(f"embed={_render_embed(node.embed)}")

    if options := node.options.kwargs:
        parts.append(f"options={render_value(options)}")

    if len(node.resources):
        parts.append(f"resources={render_value(node.resources)}")

    if node.label is not None:
        parts.append(f"label={node.label!r}")

    return f"ModuleNode({', '.join(parts)})"


def _render_edges(edges: tuple[Edge, ...]) -> str:
    """Renders the edge tuple, keeping a one-edge graph a tuple."""
    rendered = ", ".join(map(str, edges))
    return "()" if not rendered else f"({rendered},)"


def _render_outputs(outputs: Mapping[str, Endpoint]) -> str:
    """Renders the named outputs as a dict of endpoint references."""
    pairs = (f"{name!r}: {ref}" for name, ref in outputs.items())
    return "{" + ", ".join(pairs) + "}"


def _collect_raw_confs(nodes: list[ModuleNode]) -> list[str]:
    """Collects the raw config classes the workflow module has to import."""
    used: set[str] = set()

    for node in nodes:
        if (raw := _resolve_raw_conf(node.name, node.conf)) is not None:
            used.add(raw)

        if node.embed is not None:
            embed_conf = node.embed["conf"]
            used.add("Embed")

            if (raw := _resolve_raw_conf(node.embed["name"], embed_conf)) is not None:
                used.add(raw)

    return sorted(used)


def compile_workflow(
    workflow: WorkflowLike, name: str = "anonymous", *, is_async: bool = False
) -> WorkflowModule:
    """
    Generates the ``WorkflowModule`` that rebuilds and runs ``workflow``.

    A ``RawWorkflow`` is normalized into a ``Workflow`` first. This way module always
    reflects the normalized graph rather than the shorthand it was written in. The
    module declares the workflow with typed configuration classes and exposes a
    single ``pipe`` (or ``async_pipe``) callable over it. That callable takes one
    item, a stream, or nothing; reports the workflow's input declarations and the
    modules and stored workflows it uses in the describe modes; and otherwise yields
    the items produced at the workflow's default output.

    Args:

        workflow: The ``Workflow``, or a ``RawWorkflow`` describing one.
        name: The name the module documents itself by.
        is_async: Whether to generate the asynchronous interface.

    Returns:

        The formatted ``WorkflowModule``.

    Raises:

        InvalidPipelineError: If the workflow is invalid, or carries a node family
            that cannot be generated yet.

    Examples:

        >>> raw = {"nodes": [{"name": "forever"}]}
        >>> source = compile_workflow(raw, "pipe_demo")
        >>> print(next(l for l in source.splitlines() if l.startswith("DEPEND")))
        DEPENDENCIES: list[str] = ["forever"]
        >>> source = compile_workflow(raw, "pipe_demo", is_async=True)
        >>> print(next(l for l in source.splitlines() if l.startswith("async")))
        async_pipe = build_workflow_pipes(

    """
    workflow = normalize_workflow(workflow)
    workflow.validate()
    workflow.require_module_only("code generation")
    nodes = list(workflow.module_nodes.values())
    edge_names = sorted({type(edge).__name__ for edge in workflow.edges})
    loader = PackageLoader("riko.runtime")
    env = Environment(loader=loader, autoescape=False)  # noqa: S701
    template = env.get_template("pyworkflow.txt")

    rendered = template.render(
        pipe_name=pythonise(name),
        is_async=is_async,
        ext_names=sorted({"ModuleNode", *edge_names}),
        raw_confs=_collect_raw_confs(nodes),
        nodes=[_render_node(node) for node in nodes],
        edges=_render_edges(workflow.edges),
        outputs=_render_outputs(workflow.outputs),
        inputs=render_value(workflow.inputs),
        resources=render_value(list(workflow.resources)),
        has_resources=len(workflow.resources) > 0,
        dependencies=render_value(sorted({node.name for node in nodes})),
        subtype="transformer" if len(workflow.inputs) else "source",
    )

    return WorkflowModule(ruff_format(rendered))


__all__ = ["RAW_CONFS", "compile_workflow", "render_value"]
