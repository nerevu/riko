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
        "materialize",
        "run",
    }
)

IO_ = frozenset(
    {
        "async_get_temp_file",
        "async_get_temp_path",
        "async_url_open",
        "async_write",
        "get_temp_file",
        "get_temp_path",
    }
)

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
        "PortEdge",
        "Endpoint",
        "ExecutionSettings",
        "Executor",
        "FeedType",
        "IdentityMode",
        "RikoNode",
        "OneShotResource",
        "Pipeline",
        "Resource",
        "ReusableResource",
        "SortableCastType",
        "UserAgent",
        "Workflow",
        "WorkflowLike",
        "WorkflowDocument",
        "WorkflowModule",
        "WriteMode",
        "get_path",
        "list_module_metadata",
        "list_modules",
    }
)

ROOT_EXCEPTIONS = frozenset(
    {
        "EmptyPipelineError",
        "InvalidPipelineError",
        "PipelineError",
        "PipelineStateError",
        "RemovedOptionError",
        "RikoError",
        "UnsupportedModuleError",
        "UnsupportedTargetError",
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
        "normalize_module_name",
        "operator",
        "processor",
        "register_module",
        "temporary_registrations",
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
        "temporary_registrations",
    }
)

EXT_WORKFLOWS = frozenset(
    {
        "ActionNode",
        "CacheNode",
        "CallableNode",
        "Dispatcher",
        "ModuleNode",
        "PublishEdge",
        "ReadNode",
        "StreamEdge",
        "SubscribeNode",
        "WriteNode",
        "register_workflow_store",
        "resolve_inputs",
        "temporary_registrations",
        "workflow",
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
        "ResourceStrategy",
        "AsyncStream",
        "AsyncItems",
        "AsyncPipeTuples",
        "CallOptions",
        "CallOptionsLike",
        "Conf",
        "CustomUserAgent",
        "DagModule",
        "Embed",
        "EventSink",
        "Feed",
        "InputLike",
        "InputSchema",
        "InputSchemaLike",
        "Item",
        "Items",
        "PipelineRun",
        "PipelineStream",
        "RawEdge",
        "RawEndpoint",
        "RawInputSchema",
        "RawNode",
        "RawWorkflow",
        "PipeDag",
        "PipeDef",
        "PipeDefLike",
        "PipeTuples",
        "RawCallOptions",
        "Stream",
        "SyncPipeTuples",
        "FeedTypeLike",
        "UserAgentLike",
    }
)
