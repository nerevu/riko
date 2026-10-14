"""
Provides internal tests: mechanics, drift guards, and failure modes.

Index (file, then the subjects it owns, in file order):

    test_execution.py         SyncExecution, ResourceAcquisition, LifecycleFactory,
                              ValueFactory, Values, ResourceEcosystem,
                              ResourceImmutability, WorkerCnt, PoolHandle, OpenPool,
                              ExecutionSettings, MappingPolicy, SyncConcurrency
    test_execution_plan.py    ExecutionPlan, ResolvedModule, EmbedAdaptation,
                              PlanRun, Embed, PreparedCall
    test_definitions.py       FrozenDict, Context, ResourceFreezing, ResourceView,
                              ResourceBinding, Nodes, WorkflowFields,
                              NormalizeInternals, RawWorkflowFields,
                              ExecutionPlanFields, PipelineDefinitionFields,
                              RequireHelpers, RequireFromForm, ResolveEnum,
                              NormalizeStrs, FieldNames, TypedDictKeys, WriteMode,
                              Formats, WriteOperation, WriteCapabilities,
                              NormalizeTarget, RegisterTarget, ResolveFormat,
                              FileCapabilities, ValidateTargetMode, BuildWrite,
                              ConverterPath, Csv, Jsonl, Framed, SessionLifecycle,
                              WriteExecution, Sink
    test_values.py            CanonicalBytes, Digest, ReprCache, CastDatetime,
                              Fromdict, TryLocalTz, Dates, DotDict, Parsers, RSSUtils,
                              Graph, GraphIndex
    test_io.py                Fetch, LoopbackServer, AsyncUrlOpen,
                              ExtensionlessAsyncUrlOpen, Reencode, ConversionFuncs,
                              AsyncMapStream, AsyncMap, AsyncMerge, GatherResults,
                              AsyncTimeoutIterator
    test_modules.py           IsasyncInferenceValid, InvalidCombinations,
                              AsyncGeneratorSource, AsyncOperatorReturnsStreamDirectly,
                              AsyncProcessorDualProtocol, ProcessorListKeepsTestFlag,
                              BareDecorator, Splitter, AsyncOperatorLaziness,
                              ReturnInference, ModuleMetadata, WrapperMeta,
                              LoopCharacterization, ProcessorTopLevelCount,
                              ImplicitLooping, SubpipeLoop, AsyncLoop, CustomEmbed,
                              ModuleRegistry, PublicRegister, ResolverDispatcher,
                              RequireInterface, EntryPointModules, WorkflowResolver,
                              Catalog, ResolvedDocuments, Modules, Prepare
    test_codegen.py           WorkflowModule, WorkflowModuleDescribe, CompileWorkflow,
                              Pythonise, ModuleCategory, EnumMemberName,
                              GenerateModuleNames, GenerateModuleIds, ConfigCodegen,
                              WorkflowFixtures, WorkflowProbes
    test_cli.py               CodegenCommand, UpgradeCommand, ImportsCommand,
                              LintCommand, CoverageRatchet, ConsoleScripts, Docstyle,
                              TermLint, LiteralLint, LayoutLint, DependencyLint,
                              HookPinLint, CanonicalImportLint, RelativeImportLint,
                              ImportArchitectureLint, ValidateGraph, RequireWorkflow,
                              ReadDocument, Timeouts
"""
