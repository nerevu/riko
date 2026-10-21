"""
Provides internal tests: mechanics, drift guards, and failure modes.

Index (file, then the subjects it owns, in file order):

    test_cli.py               CodegenCommand, UpgradeCommand, ImportsCommand,
                              LintCommand, CoverageRatchet, ConsoleScripts, Docstyle,
                              CitationLint, TermLint, LiteralLint, BindingLint,
                              TierIndexCodegen, LayoutLint, BasenameLint,
                              DependencyLint, HookPinLint, CanonicalImportLint,
                              RelativeImportLint, ImportArchitectureLint, ValidateGraph,
                              RequireWorkflow, ReadDocument, Timeouts, LogLevel
    test_codegen.py           WorkflowModule, WorkflowModuleDescribe, CompileWorkflow,
                              Pythonise, ModuleCategory, EnumMemberName,
                              GenerateModuleNames, GenerateModuleIds, ConfigCodegen,
                              WorkflowFixtures, WorkflowProbes
    test_concurrency.py       ExecutionSettings, MappingPolicy, SyncConcurrency
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
    test_execution.py         SyncExecution, ResourceAcquisition, LifecycleFactory,
                              ValueFactory, Values, ResourceEcosystem,
                              ResourceImmutability
    test_execution_plan.py    ExecutionPlan, ResolvedModule, EmbedAdaptation, PlanRun,
                              Embed, PreparedCall
    test_io.py                Fetch, LoopbackServer, AsyncUrlOpen,
                              ExtensionlessAsyncUrlOpen, Reencode, ConversionFuncs,
                              AsyncMapStream, AsyncMap, AsyncMerge, GatherResults,
                              AsyncTimeoutIterator
    test_modules.py           IsasyncInferenceValid, InvalidCombinations,
                              AsyncGeneratorSource, AsyncOperatorReturnsStreamDirectly,
                              AsyncProcessorDualProtocol, ProcessorListKeepsTestFlag,
                              ProcessorSkipIf, BareDecorator, ParserSignature, Splitter,
                              AsyncOperatorLaziness, ReturnInference, ModuleMetadata,
                              WrapperMeta, WorkflowDecorator, LoopCharacterization,
                              ProcessorTopLevelCount, ImplicitLooping, SubpipeLoop,
                              AsyncLoop, CustomEmbed, ModuleRegistry, PublicRegister,
                              ResolverDispatcher, RequireInterface, EntryPointModules,
                              WorkflowResolver, Catalog, ResolvedDocuments, Modules,
                              Prepare
    test_values.py            CanonicalBytes, Digest, ReprCache, CastDatetime,
                              ResolveCastType, DefItemgetter, Fromdict, TryLocalTz,
                              Dates, DotDict, Parsers, RSSUtils, Graph, GraphIndex,
                              Logging
"""
