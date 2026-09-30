# vim: sw=4:ts=4:expandtab
"""
Generates a Python module from a canonical Workflow v2 graph.

The generated module rebuilds the workflow from typed configuration classes and
exposes a ``pipe``/``async_pipe`` callable that runs it through the canonical
execution. It is a readable, type-checkable rendering of the same graph, so it may
be edited by hand, imported like any module, and embedded in a loop as a sub-pipe.

Examples:

    Basic usage::

        >>> from riko.definitions._workflow import Pipeline
        >>> from riko.runtime._codegen import compile_workflow
        >>>
        >>> attrs = {"key": "title", "value": "riko"}
        >>> flow = Pipeline.from_module("itembuilder", conf={"attrs": attrs})
        >>> flow = flow.pipe("rename", conf={"rule": [{"field": "title"}]})
        >>> source = compile_workflow(flow.spec, "pipe_demo")
        >>> print(next(l for l in source.splitlines() if l.startswith("def pipe")))
        def pipe(item=None, context: Context | None = None, **_):
        >>> print(next(l for l in source.splitlines() if l.startswith("DEPEND")))
        DEPENDENCIES: list[str] = ["itembuilder", "rename"]

"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jinja2 import Environment, PackageLoader

from riko.base._source_format import ruff_format
from riko.base._strutils import pythonise
from riko.base.exceptions import InvalidPipelineError
from riko.definitions._workflow import ModuleNode, WorkflowSpec
from riko.types._guards import is_mapping

from ._normalize import normalize_workflow

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from riko.types._collections import FrozenConf
    from riko.types._workflow import Edge, Endpoint, WorkflowSpecLike
    from riko.types.modules import Conf, Embed

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
    """Renders one node as the keyed ``ModuleNode(...)`` entry that rebuilds it."""
    parts = [f"id={node.id!r}", f"name={node.name!r}"]

    if len(node.conf):
        parts.append(f"conf={_render_conf(node.name, node.conf)}")

    if node.embed is not None:
        parts.append(f"embed={_render_embed(node.embed)}")

    if len(node.options):
        parts.append(f"options={render_value(node.options)}")

    if len(node.resources):
        parts.append(f"resources={render_value(node.resources)}")

    if node.label is not None:
        parts.append(f"label={node.label!r}")

    return f"{node.id!r}: ModuleNode({', '.join(parts)})"


def _render_edges(edges: tuple[Edge, ...]) -> str:
    """Renders the edge tuple, keeping a one-edge graph a tuple."""
    rendered = ", ".join(map(str, edges))
    return "()" if not rendered else f"({rendered},)"


def _render_outputs(outputs: Mapping[str, Endpoint]) -> str:
    """Renders the named outputs as a dict of endpoint references."""
    pairs = (f"{name!r}: {ref}" for name, ref in outputs.items())
    return "{" + ", ".join(pairs) + "}"


def _gen_module_nodes(spec: WorkflowSpec) -> Iterator[ModuleNode]:
    """Emits every node, rejecting a family that has no generated form yet."""
    for node in spec.nodes.values():
        if isinstance(node, ModuleNode):
            yield node
        else:
            msg = f"cannot generate a pipe for a {node.family} node; "
            msg += "only registered module nodes can be generated so far"
            raise InvalidPipelineError(msg)


def _resolve_raw_confs(nodes: list[ModuleNode]) -> list[str]:
    """Collects the raw config classes the generated module has to import."""
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
    spec: WorkflowSpec, name: str = "anonymous", *, is_async: bool = False
) -> str:
    """
    Generates the Python module source that rebuilds and runs ``spec``.

    The module declares the workflow with typed configuration classes and exposes a
    single ``pipe`` (or ``async_pipe``) callable over it. That callable takes one
    item, a stream, or nothing, reports the workflow's inputs and module
    dependencies in the describing modes, and otherwise yields the items produced
    at the workflow's default output.

    Args:

        spec: The canonical workflow to generate a module for.
        name: The name the generated module documents itself by.
        is_async: Whether to generate the asynchronous interface.

    Returns:

        The formatted Python source of the generated module.

    Raises:

        InvalidPipelineError: If the workflow is invalid, or carries a node family
            that cannot be generated yet.

    Examples:

        >>> from riko.definitions._workflow import Pipeline
        >>>
        >>> flow = Pipeline.from_module("forever")
        >>> source = compile_workflow(flow.spec, "pipe_demo", is_async=True)
        >>> print(next(l for l in source.splitlines() if l.startswith("async def a")))
        async def async_pipe(item=None, context: Context | None = None, **_):

    """
    spec.validate()
    nodes = list(_gen_module_nodes(spec))
    edge_names = sorted({type(edge).__name__ for edge in spec.edges})
    loader = PackageLoader("riko.runtime")
    env = Environment(loader=loader, autoescape=False)  # noqa: S701
    template = env.get_template("pyworkflow.txt")

    rendered = template.render(
        pipe_name=pythonise(name),
        is_async=is_async,
        definition_names=sorted({"ModuleNode", "WorkflowSpec", *edge_names}),
        raw_confs=_resolve_raw_confs(nodes),
        nodes=[_render_node(node) for node in nodes],
        edges=_render_edges(spec.edges),
        outputs=_render_outputs(spec.outputs),
        inputs=render_value(spec.inputs),
        resources=render_value(list(spec.resources)),
        has_resources=len(spec.resources) > 0,
        dependencies=render_value(sorted({node.name for node in nodes})),
        subtype="transformer" if len(spec.inputs) else "source",
    )

    return ruff_format(rendered)


def compile_pipe(
    workflow: WorkflowSpec | WorkflowSpecLike,
    name: str = "anonymous",
    *,
    is_async: bool = False,
) -> str:
    """
    Generates the Python module source for a workflow or an authoring mapping.

    An authoring mapping is normalized into a canonical workflow first, so the
    generated module always reflects the canonical graph rather than the shorthand
    it was written in.

    Args:

        workflow: The canonical workflow, or an authoring mapping describing one.
        name: The name the generated module documents itself by.
        is_async: Whether to generate the asynchronous interface.

    Returns:

        The formatted Python source of the generated module.

    Raises:

        InvalidPipelineError: If the workflow is invalid, or carries a node family
            that cannot be generated yet.

    Examples:

        >>> authoring = {"nodes": [{"name": "forever"}]}
        >>> source = compile_pipe(authoring, "pipe_demo")
        >>> print(next(l for l in source.splitlines() if l.startswith("DEPEND")))
        DEPENDENCIES: list[str] = ["forever"]

    """
    spec = normalize_workflow(workflow)
    return compile_workflow(spec, name, is_async=is_async)


__all__ = ["RAW_CONFS", "compile_pipe", "compile_workflow", "render_value"]
