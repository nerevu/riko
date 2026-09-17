# vim: sw=4:ts=4:expandtab
"""Private declarations describing Riko's supported API contracts."""

BADO = frozenset(
    {
        "as_async",
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

IO_ = frozenset({"async_url_open", "async_write", "get_async_temp_file"})

COLLECTIONS = frozenset(
    {
        "AsyncCollection",
        "AsyncPipe",
        "Formats",
        "PipeState",
        "SyncCollection",
        "SyncPipe",
        "export",
        "list_formats",
    }
)

COMPILE = frozenset(
    {
        "build_pipeline",
        "compile_pipe",
        "convert_dag",
        "extract_dependencies",
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
        "ExecutionMode",
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
        "AsyncOperatorWrapper",
        "AsyncProcessorWrapper",
        "AsyncSplitterWrapper",
        "DynamicConf",
        "FileTarget",
        "ModuleDefinition",
        "ModuleMetadata",
        "ModuleName",
        "ModuleNameLike",
        "ModuleRegistry",
        "ModuleSubtype",
        "ModuleType",
        "ModuleWrapper",
        "SupportsActions",
        "SupportsRead",
        "SupportsWrite",
        "SyncOperatorWrapper",
        "SyncProcessorWrapper",
        "SyncSplitterWrapper",
        "Target",
        "TargetRegistry",
        "WriteCapabilities",
        "derive_category",
        "get_conf_type",
        "resolve_module_name",
        "operator",
        "processor",
        "register_module",
        "register_target",
        "splitter",
    }
)

TYPES = frozenset(
    {"AsyncStream", "Conf", "Feed", "Item", "Items", "PipeTuples", "Stream"}
)
