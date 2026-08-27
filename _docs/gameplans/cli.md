# CLI gameplan

## 1. Mission

Create a separate `riko-cli` package that provides one coherent command-line interface for
the Riko ecosystem without becoming another application monolith.

The CLI supports inspection/validation/execution of Riko pipelines, plugin commands,
MCP/OpenAPI capabilities, AI workflows/conversations, site tooling, artifacts, reproducible
noninteractive workflows, and optional command-shell behavior.

The CLI owns:

* Click argument parsing and command discovery;
* configuration assembly;
* immutable Riko `Context` construction;
* terminal interaction/approval prompts;
* output/event rendering;
* stable exit codes.

It does **not** own Riko execution internals, MCP/HTTP sessions, OpenAPI parsing, model
provider logic, AI planning, site generation, conversation reasoning, or artifact-store
implementations.

---

# 2. Package and entry point

```text
nerevu/riko-cli
riko_cli
```

```toml
[project.scripts]
riko = "riko_cli.__main__:main"
```

Optional packages remain independently installable/discoverable (`riko-mcp`, `riko-ai`,
`riko-site`, etc.). Root help/version/config must not eagerly import their heavy SDKs.

---

# 3. Prerequisites

Riko provides:

* immutable reusable `Pipeline[T]` definitions;
* private sync/async executions created by iteration;
* immutable public `Context` / `Resource` definitions;
* module/export registries;
* pipeline validation/description/execution APIs;
* execution configuration, cancellation/deadlines, events, resources, and state through
  supported public contracts.

There is no public `ExecutionContext` prerequisite.

Optional packages expose reusable service/domain APIs; CLI adapters must not duplicate
missing service-layer behavior.

---

# 4. Architectural rule

The CLI is a thin adapter over reusable application services.

```python
async def plan_command(
    request: ApiPlanRequest,
    *,
    context: CliContext,
) -> CommandResult:
    outcome = await context.services.capabilities.plan(
        request,
        context=context.riko,
    )
    return CommandResult(data=outcome)
```

Substantial operations must also be callable from Python, MCP/server adapters, notebooks,
tests, and scheduled automation without invoking the CLI parser.

---

# 5. Base implementation choices

## 5.1 Click-native parsing

Use Click as the command framework. The extension API is Click-native end-to-end; do not
define an argparse compatibility contract or pass `argparse.Namespace` / `ArgumentParser`
objects through plugin/domain APIs.

Convert Click values into typed request/domain objects at the command adapter boundary.

## 5.2 Configuration

Use `tomllib`, `pathlib`, and environment handling directly. Do not require a configuration
framework.

## 5.3 Async entry point

One top-level AnyIO boundary:

```python
def main() -> int:
    return anyio.run(main_async)
```

Commands/services do not start nested private event loops.

## 5.4 Optional terminal enhancements

Rich/prompt-toolkit or equivalent enhancements are optional. Click's supported completion
mechanism should be used rather than introducing a second parser/completion model. Optional
renderers cannot alter command data or exit-code contracts.

---

# 6. Click-native command plugin system

Packages register command providers through entry points:

```toml
[project.entry-points."riko.commands"]
mcp = "riko_mcp.cli:provider"
ai = "riko_ai.cli:provider"
site = "riko_site.cli:provider"
```

Minimal protocol:

```python
class CommandProvider(Protocol):
    name: str
    distribution: str
    api_version: int

    def commands(self) -> tuple[click.Command, ...]: ...
```

Providers may return `click.Command` / `click.Group` objects. Nested command structure is
therefore expressed by Click itself instead of a second `CommandSpec.configure(parser)`
layer.

Built-in commands use the same registration path internally.

### Collision policy

Top-level and nested command paths must resolve uniquely. Registry construction fails with
both provider/distribution identities on a collision; installation order never silently
wins. Test-only registration may allow explicit replacement, but installed plugins do not
replace built-ins by default.

### Lazy imports

`riko --help` must not eagerly import model SDKs, MCP transports, database clients, site
engines, etc. Heavy dependencies are imported only when the relevant command runs.

---

# 7. CLI application context

`CliContext` is a CLI-owned adapter context, not a Riko execution context:

```python
@dataclass(slots=True, kw_only=True)
class CliContext:
    riko: Context
    output: OutputWriter
    events: CliEventSink
    prompts: PromptService
    configuration: CliConfiguration
    project: ProjectContext
    services: ServiceRegistry
```

The immutable Riko `Context` holds definitions/configuration and declared resources. A
pipeline/service execution creates its private runtime state only when actually executed.

Project context remains simple immutable filesystem metadata:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectContext:
    root: Path
    working_directory: Path
    riko_directory: Path
```

Project detection walks upward from the current directory and prefers the nearest `.riko/`,
`pyproject.toml`, or `.git/` marker. `--project` overrides it without silently changing the
process working directory.

---

# 8. Configuration precedence

```text
package defaults
→ user configuration
→ project configuration
→ explicit --config files, in order
→ environment variables
→ command-line arguments
```

Suggested user/project locations remain `$XDG_CONFIG_HOME/riko/` and `.riko/`.
Package-specific files remain owned by their packages (`mcp.toml`, `ai.toml`, `site.toml`).

The CLI normalizes resolved configuration into immutable `Context` / package request objects.
It does not inject mutable runtime clients into a public `ExecutionContext`.

Resolved secrets never appear in config display, debug dumps, tracebacks, machine output,
plans, command history, or conversation exports. Credential references are preferred over
command-line secret values.

Commands:

```text
riko config paths
riko config show
riko config validate
```

`config show --sources` may report the source of each non-secret value.

---

# 9. Global options

Keep global options stable and limited:

```text
--project PATH
--config PATH                 repeatable
--format FORMAT
--color auto|always|never
--log-format text|json
--verbose / -v                repeatable
--quiet / -q
--trace
--no-input
--yes
--dry-run
--deadline SECONDS
```

Human output is default. Automation formats include JSON, JSONL, and raw; YAML remains
optional.

---

# 10. Output contract

`stdout` contains primary command output; `stderr` contains logs/progress/warnings/prompts.
JSON stdout must contain only valid JSON/JSONL.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CommandResult:
    data: JsonValue | None = None
    summary: str | None = None
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    exit_code: int = 0
```

Handlers return domain data, not preformatted terminal strings. Deterministic JSON
serialization supports public dataclasses/enums/paths/datetime/Decimal/mappings/sequences and
explicit public JSON protocols. Unknown objects raise a structured serialization error;
JSON mode never falls back to `repr()`.

---

# 11. Event rendering

Long-running services emit structured events. The CLI owns rendering/subscription hooks, not
Riko's private execution object.

A service/Pipeline run receives the CLI event sink through the supported public Context or
execution-configuration/service adapter boundary. Do not construct or expose:

```python
ExecutionContext(event_sink=...)
```

Human mode may render interactive progress on a TTY; JSONL emits structured event records;
noninteractive mode uses stable stderr/JSONL without animation.

---

# 12. Error and exit-code contract

Stable exit codes:

```text
0    success
1    unexpected internal failure
2    usage/configuration error
3    validation failure
4    approval required/denied
5    execution failure
6    partial success
7    missing plugin/optional dependency
8    unavailable external service
9    budget/policy rejection
130  interrupted by user
```

Structured errors contain a stable code/message/details/exit code/retryable flag. `--trace`
adds traceback diagnostics to stderr after redaction.

---

# 13. Approval

`riko-cli` supplies a prompt/approval implementation to owning services:

```python
class PromptService(Protocol):
    async def approve(self, request: ApprovalRequest) -> ApprovalDecision: ...
```

Approval display includes capability/origin/host, redacted arguments, effects, relevant
schema/plan identity, rationale, and output shape.

`--yes` may confirm only actions already allowed by active policy. It never grants private
network access, destructive permission, missing credentials, or validation bypass.

`--no-input` never hangs or assumes approval; required approval returns exit code 4.

Initial approval scopes may be `ONCE` and `CONVERSATION`. Persistent approval state remains
owned by the relevant package/service.

---

# 14. Built-in command tree

```text
riko version
riko help
riko commands list
riko plugins list
riko plugins inspect NAME
riko config paths
riko config show
riko config validate
riko doctor

riko modules list
riko modules describe NAME
riko modules schema NAME

riko exports list
riko exports describe NAME

riko pipeline validate FILE
riko pipeline describe FILE
riko pipeline run FILE

riko artifacts inspect URI
riko artifacts copy URI PATH
riko artifacts hash URI
```

Pipeline validation/description do not execute. Execution resolves the pipeline definition
and uses normal iteration/private execution semantics.

Where a run service is used, canonical Python constructs:

```python
PipelineRunRequest(
    pipeline=PipelineRef("daily-report"),
    ...,
)
```

Serialized CLI/workflow shorthand may use strings only after compiler/configuration
resolution; runtime service code does not guess bare-string reference kinds.

---

# 15. `riko-mcp` commands

Registered by `riko-mcp` as Click commands/groups:

```text
riko mcp servers
riko mcp inspect SERVER
riko mcp tools SERVER
riko mcp resources SERVER
riko mcp prompts SERVER
riko mcp refresh SERVER
riko mcp call SERVER TOOL
riko mcp read SERVER URI

riko capabilities list
riko capabilities search QUERY
riko capabilities inspect ID
riko capabilities refresh
riko capabilities execute PLAN
riko capabilities history

riko api search QUERY
riko api candidates QUERY
riko api schemas QUERY --top N
riko api inspect-schema ID
riko api operations SCHEMA_ID
riko api normalize FILE
riko api execute PLAN
```

Inspection/discovery never implies execution. The CLI does not generate Python functions
from OpenAPI operations.

---

# 16. `riko-ai` commands

Registered by `riko-ai`:

```text
riko ai infer
riko ai summarize
riko ai verify
riko ai research
riko ai select
riko ai plan
riko ai plan validate FILE
riko ai plan execute FILE
riko ai profiles list/show/validate
riko ai evaluate FILE
riko ai evaluation show/compare
```

Selection/planning remains separate from execution.

Agent-style iterative behavior in service implementations reuses ordinary Riko `Pipeline`
/`loop`; the CLI never builds an `AgentGraph`.

---

# 17. Workflow commands

```text
riko workflow validate FILE
riko workflow describe FILE
riko workflow run FILE
```

A pipeline is a Riko Pipeline definition. A higher-level workflow may include discovery,
AI selection, planning, verification, approval, and one or more explicit run requests.
Schemas/services remain owned by Riko / `riko-ai` / `riko-mcp`; command dispatch remains
owned by `riko-cli`.

---

# 18. Conversation CLI

`riko-ai` owns conversation model/runner/memory/persistence/planning/model turns;
`riko-mcp` owns validated capability execution; `riko-cli` owns terminal input, rendering,
approval prompts, and command adapters.

```text
riko chat
riko chat --profile PROFILE
riko chat --resume ID
riko chat list/show/export/delete
riko chat run ...
```

Conversation stores remain `riko-ai` services. The CLI selects/configures them; it does not
reimplement persistence.

Conversation events are rendered structurally and provider streaming objects do not leak
through the CLI boundary. Workflow extraction must omit credentials, hidden model reasoning,
transient sessions, and conversation-only approvals.

---

# 19. Site plugin

`riko-site` registers Click commands for validate/assemble/build/preview/serve, route/manifest
inspection, drafts, and review actions. The CLI calls reusable site services; preview server
implementation stays in `riko-site`.

---

# 20. Non-AI command shell

A later `riko shell` may tokenize input with `shlex` and dispatch through the same Click
command registry. It must not create a second command implementation or support arbitrary OS
shell escape initially.

---

# 21. Old CLI migration

Old monolithic responsibilities are split by ownership:

| Old responsibility | New owner |
|---|---|
| terminal parsing/output | `riko-cli` |
| model/provider routing | `riko-ai` |
| conversations/workflows/evaluations | `riko-ai` adapters |
| MCP/OpenAPI/capability execution | `riko-mcp` |
| APIs.guru discovery | `riko-mcp` |
| oversized result storage | artifact service |
| unsandboxed Python | replaced by sandboxed capability |
| multi-agent supervision | Pipeline/loop-based bounded workflow services |

Do not preserve generated OpenAPI Python functions or the old command monolith for
compatibility.

---

# 22. Logging and diagnostics

Logs go to stderr. `-v` / `-vv` raise verbosity; `--trace` includes traceback diagnostics.
JSON logging remains machine-readable.

`riko doctor` inspects Python/Riko versions, command plugins/API compatibility, optional
dependencies, configuration/project paths, writable data/cache paths, and integration
configuration without exposing keys. External network probes require explicit `--network`.

Where a configured state store is relevant, diagnostics may report its coarse
`StateStoreCapabilities` (serialization, persistent, portable) without leaking state values.

---

# 23. Cache/data directories

Support XDG-style configuration/data/cache/state locations plus `.riko/` project-local
configuration/artifacts/cache/state. A small cross-platform path utility (optionally
`platformdirs`) is acceptable.

---

# 24. Security rules

The CLI must not evaluate Python from arguments, execute arbitrary shell commands, accept
model-generated subprocess commands, print secrets, auto-approve destructive operations,
execute stale/unvalidated plans, accept model-selected arbitrary schema URLs, or weaken
network/security policy through convenience flags.

Prefer credential references:

```text
--credential exchange_api
```

over plaintext command-line keys. When sensitive input is unavoidable, prefer environment,
stdin, terminal secret prompt, or secret-provider references.

---

# 25. Repository layout

```text
riko_cli/
├── __main__.py
├── app.py
├── context.py
├── exceptions.py
├── exit_codes.py
├── commands/
│   ├── registry.py
│   └── builtin/
├── config/
├── output/
├── events/
├── prompts/
├── services/
└── testing/
```

Package-specific Click command adapters stay in their owning packages (`riko_mcp/cli/`,
`riko_ai/cli/`, `riko_site/cli/`). A separate argparse-style `specification.py` layer is not
part of the target architecture.

---

# 26. Implementation phases

```text
C0  architecture + command inventory
C1  Click-native application/provider registry/collision/version checks
C2  configuration/project detection/redaction + immutable Context construction
C3  output/events/errors/prompts/approval
C4  core Riko inspection/validation/run/artifact commands
C5  MCP/capability/OpenAPI Click plugins
C6  AI/workflow Click plugins
C7  conversation CLI adapter
C8  site command plugin
C9  non-AI shell reusing Click registry
C10 generated command docs/completion/examples
C11 optional rich TUI after line-oriented CLI stabilizes
```

C1 acceptance specifically requires third-party packages to register native Click commands
without argparse adapters. C2 acceptance requires no public `ExecutionContext` construction.

---

# 27. Pull-request sequence

Keep CLI adapters separate from unrelated domain refactors. Suggested progression:

```text
riko-cli
    cli-architecture-and-click-registry
    cli-config-and-context
    cli-output-events-and-errors
    cli-core-riko-commands
    cli-chat-adapter
    cli-shell
    cli-docs-and-completion

riko-mcp
    cli-mcp-inspection
    cli-capability-catalog
    cli-openapi-discovery
    cli-capability-execution

riko-ai
    cli-infer-and-models
    cli-capability-selection
    cli-workflows
    cli-conversations
    cli-evaluations

riko-site
    cli-site-build
    cli-site-review
    cli-site-exporters
```

---

# 28. Testing strategy

Unit/contract tests cover Click command/group registration, nested paths, collisions, plugin
API-version mismatch, configuration precedence/project detection/redaction, serialization,
exit codes, noninteractive prompts, and approval scopes.

CLI integration tests invoke the real console entry point and assert stdout/stderr/exit
codes/JSON validity/redaction for root help, version, command listing, module listing,
pipeline validation, and config display.

Plugin fixtures include valid, duplicate, incompatible-version, missing-dependency, and
failing-handler providers.

Conversation/site/MCP integrations use deterministic fake service implementations. Terminal
coverage includes TTY/non-TTY, redirected progress, Ctrl-C/EOF, and optional completion.
Snapshots normalize nondeterministic timestamps/IDs/terminal width and never contain
secrets.

---

# 29. Performance requirements

Measure base startup, root help, plugin discovery, config loading, and dispatch. Root help
must avoid network calls and optional provider SDK imports. A sub-second target is required;
the initial aspirational target remains roughly 250 ms on a typical development machine,
excluding cold-Python variability.

---

# 30. Definition of done

1. Plugin APIs are Click-native; no argparse contract remains.
2. CLI constructs immutable public `Context`, never public `ExecutionContext`.
3. Pipeline execution uses the single Pipeline/private-execution architecture.
4. Canonical orchestration requests use `PipelineRef` rather than runtime string guessing.
5. JSON/stdout, stderr/logging, exit codes, approval, and redaction contracts are stable.
6. Heavy package SDKs remain lazy and root help is fast/offline.
7. MCP/AI/site/conversation business logic stays in reusable owning-package services.
8. The shell/TUI reuse the same command/service contracts rather than creating another CLI.
