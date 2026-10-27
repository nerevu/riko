"""
Provides public API tests: tests that use only supported names.

Index (file, then the subjects it owns, in file order):

    test_modules.py     Input, Fetchdata, Filter, Slugify, Join, Sort, Send,
                        AsyncReceive, RequiredOperands, ListModules, DescribeModule,
                        ImportSurface
    test_pipeline.py    PipelineConstruction, PipelineChaining, ModuleNameEnum,
                        PipelineIteration, OutputParity, Reiteration, Close, Failure,
                        AsyncSourceAdapter, Alist, FanIn, WithExecution,
                        ExecutionSettings, AsyncBoundedParallel, AsyncFanInParallel,
                        ContextMode, ContextImmutability, EnvironmentBinding,
                        Subscriptions, Split, CallableNodes, ConditionalNodes,
                        UnseededPipeline
    test_workflow.py    Workflow, NodeFamily, ParsePort, WorkflowParse, PipeDag,
                        NormalizeWorkflow, RequireRunnableOnly, CallableNodeDocuments,
                        Validate, Migrate, Serialize, WorkflowDocumentResolution
    test_write.py       WritePassthrough, WriteParity, WriteNestedItems, WriteSetValues,
                        WriteSkips, WriteTargetFromExtension, PipelineWriteDefinition,
                        PipelineWrite, ExportFormats, ExportPipeline, ExportFinance
"""
