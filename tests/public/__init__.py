"""
Provides public API tests: tests that use only supported names.

Index (file, then the subjects it owns, in file order):

    test_pipeline.py    PipelineConstruction, PipelineChaining, ModuleNameEnum,
                        PipelineIteration, OutputParity, Reiteration, Close, Failure,
                        AsyncSourceAdapter, FanIn, WithExecution, ExecutionSettings,
                        AsyncBoundedParallel, AsyncFanInParallel, ContextMode,
                        ContextImmutability, EnvironmentBinding, WritePassthrough,
                        WriteParity, WriteNestedItems, WriteSetValues, WriteSkips,
                        WriteTargetFromExtension, PipelineWriteDefinition,
                        PipelineWrite, ExportFormats, ExportPipeline, ExportFinance,
                        Subscriptions, Split, CallableNodes, ConditionalNodes,
                        UnseededPipeline
    test_workflow.py    Workflow, NodeFamily, ParsePort, WorkflowParse, PipeDag,
                        NormalizeWorkflow, Validate, Migrate, Serialize,
                        WorkflowDocumentResolution
    test_modules.py     Input, Fetchdata, Filter, Join, Sort, Send, AsyncReceive,
                        RequiredOperands, ListModules, DescribeModule, ImportSurface
"""
