# vim: sw=4:ts=4:expandtab
"""Private declarations describing Riko's supported API contracts."""

BADO = frozenset(
    {
        "alist",
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

EXPORT = frozenset({"Formats", "export", "list_formats"})

COMPILE = frozenset({"compile_workflow"})

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
        "CastType",
        "Context",
        "DocumentShape",
        "Edge",
        "Endpoint",
        "ExecutionMode",
        "Executor",
        "Node",
        "Pipeline",
        "Workflow",
        "WorkflowLike",
        "WorkflowDocument",
        "WorkflowModule",
        "get_path",
        "get_temp_file",
        "list_modules",
    }
)

ROOT_EXCEPTIONS = frozenset(
    {
        "EmptyPipelineError",
        "InvalidPipelineError",
        "PipelineError",
        "PipelineStateError",
        "RikoError",
        "UnsupportedModuleError",
        "UnsupportedWorkflowError",
    }
)

STABLE = BADO | IO_ | EXPORT | COMPILE | MODULES | OTHER | ROOT_EXCEPTIONS

PRIVATE_RESOLUTION = frozenset(
    {
        "CompositeStore",
        "DirectoryStore",
        "DocumentStore",
        "MappingStore",
        "ModuleStore",
        "PackageStore",
        "ResolverDispatcher",
        "WorkflowResolver",
        "WorkflowStore",
        "dispatcher",
        "workflow_resolver",
    }
)

EXT_MODULES = frozenset(
    {
        "AsyncOperatorWrapper",
        "AsyncProcessorWrapper",
        "AsyncSplitterWrapper",
        "DynamicConf",
        "ModuleDefinition",
        "ModuleMetadata",
        "ModuleName",
        "ModuleNameLike",
        "ModuleRegistry",
        "ModuleSubtype",
        "ModuleType",
        "ModuleWrapper",
        "PreparedCall",
        "SyncOperatorWrapper",
        "SyncProcessorWrapper",
        "SyncSplitterWrapper",
        "get_conf_type",
        "get_module_category",
        "normalize_module_name",
        "operator",
        "processor",
        "register_module",
        "reset_module_registry",
        "splitter",
    }
)

EXT_TARGETS = frozenset(
    {
        "FileTarget",
        "SupportsActions",
        "SupportsRead",
        "SupportsWrite",
        "Target",
        "TargetRegistry",
        "WriteCapabilities",
        "register_target",
        "reset_target_registry",
    }
)

EXT_WORKFLOWS = frozenset(
    {
        "ActionNode",
        "CacheNode",
        "Dispatcher",
        "ModuleNode",
        "PublishEdge",
        "ReadNode",
        "StreamEdge",
        "SubscribeNode",
        "WriteNode",
        "migrate_v1_to_v2",
        "normalize_workflow",
        "register_workflow_store",
        "reset_workflow_resolver",
    }
)

EXT_CODEGEN = frozenset(
    {
        "NameEntry",
        "enum_member_name",
        "gen_catalog_entries",
        "generate_module_ids",
        "generate_module_names",
    }
)

EXTENSION = EXT_MODULES | EXT_TARGETS | EXT_WORKFLOWS

TYPES = frozenset(
    {
        "AsyncStream",
        "AsyncItems",
        "AsyncPipeTuples",
        "Conf",
        "EventSink",
        "Feed",
        "Item",
        "Items",
        "RawEdge",
        "RawEndpoint",
        "RawNode",
        "RawWorkflow",
        "PipeDag",
        "PipeDef",
        "PipeDefLike",
        "PipeTuples",
        "Stream",
        "SyncPipeTuples",
    }
)
