# vim: sw=4:ts=4:expandtab
"""Private declarations describing Riko's supported API contracts."""

BADO = frozenset(
    {
        "as_async",
        "async_chain",
        "async_map",
        "async_map_stream",
        "async_read",
        "async_return",
        "async_sleep",
        "backend",
        "isasync",
        "issync",
        "run",
    }
)

IO_ = frozenset({"async_url_open", "async_write", "async_get_temp_file"})

COLLECTIONS = frozenset({"Formats", "export", "list_formats"})

COMPILE = frozenset(
    {
        "build_pipeline",
        "compile_pipe",
        "parse_dag",
        "get_pipeline_dependencies",
        "parse_pipe_def",
    }
)

MODULES = frozenset(
    {
        "Modules",
        "Sinks",
        "Sources",
        "Transforms",
        "describe_module",
        "get_module_metadata",
    }
)

OTHER = frozenset(
    {
        "Backends",
        "Context",
        "Edge",
        "Endpoint",
        "ExecutionMode",
        "Node",
        "Pipeline",
        "Workflow",
        "WorkflowLike",
        "WorkflowDocument",
        "get_path",
        "get_temp_file",
        "list_modules",
    }
)

ROOT_EXCEPTIONS = frozenset(
    {
        "PipelineStateError",
        "RikoError",
        "UnsupportedModuleError",
        "UnsupportedPipelineError",
    }
)

STABLE = BADO | IO_ | COLLECTIONS | COMPILE | MODULES | OTHER | ROOT_EXCEPTIONS

PRIVATE_RESOLUTION = frozenset(
    {
        "CompositeStore",
        "DirectoryStore",
        "MappingStore",
        "ModuleStore",
        "PackageStore",
        "PipeResolver",
        "PipelineResolver",
        "pipe_resolver",
        "pipeline_resolver",
    }
)

EXTENSION = frozenset(
    {
        "ActionNode",
        "AsyncOperatorWrapper",
        "AsyncProcessorWrapper",
        "AsyncSplitterWrapper",
        "CacheNode",
        "DynamicConf",
        "FileTarget",
        "ModuleDefinition",
        "ModuleMetadata",
        "ModuleName",
        "ModuleNameLike",
        "ModuleNode",
        "ModuleRegistry",
        "ModuleSubtype",
        "ModuleType",
        "ModuleWrapper",
        "PublishEdge",
        "ReadNode",
        "StreamEdge",
        "SubscribeNode",
        "SupportsActions",
        "SupportsRead",
        "SupportsWrite",
        "SyncOperatorWrapper",
        "SyncProcessorWrapper",
        "SyncSplitterWrapper",
        "Target",
        "TargetRegistry",
        "WriteCapabilities",
        "WriteNode",
        "get_module_category",
        "get_conf_type",
        "migrate_v1_to_v2",
        "normalize_module_name",
        "normalize_workflow",
        "operator",
        "parse_document",
        "processor",
        "register_module",
        "register_pipeline_store",
        "register_target",
        "serialize_workflow",
        "splitter",
    }
)

TYPES = frozenset(
    {
        "AsyncStream",
        "AsyncItems",
        "AsyncPipeTuples",
        "Conf",
        "Feed",
        "Item",
        "Items",
        "RawEdge",
        "RawEndpoint",
        "RawNode",
        "RawWorkflow",
        "PipeTuples",
        "Stream",
        "SyncPipeTuples",
    }
)
