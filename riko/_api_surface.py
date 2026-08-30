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
        "async_write",
        "backend",
        "get_async_temp_file",
        "isasync",
        "issync",
        "run",
    }
)

COLLECTIONS = frozenset(
    {
        "AsyncCollection",
        "AsyncPipe",
        "PipeState",
        "SyncCollection",
        "SyncPipe",
        "Targets",
        "export",
        "list_targets",
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
        "list_modules",
    }
)

OTHER = frozenset({"Context", "ExecutionMode", "get_path", "get_temp_file"})

ROOT_EXCEPTIONS = frozenset(
    {
        "PipelineStateError",
        "RikoError",
        "UnsupportedModuleError",
        "UnsupportedPipelineError",
    }
)

STABLE = BADO | COLLECTIONS | COMPILE | MODULES | OTHER | ROOT_EXCEPTIONS

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
        "ModuleDefinition",
        "ModuleMetadata",
        "ModuleName",
        "ModuleNameLike",
        "ModuleRegistry",
        "ModuleSubtype",
        "ModuleType",
        "ModuleWrapper",
        "SyncOperatorWrapper",
        "SyncProcessorWrapper",
        "SyncSplitterWrapper",
        "derive_category",
        "get_conf_type",
        "normalize_module_name",
        "operator",
        "processor",
        "register",
        "splitter",
    }
)

TYPES = frozenset({"AsyncStream", "Conf", "Feed", "Item", "Items", "Stream"})
