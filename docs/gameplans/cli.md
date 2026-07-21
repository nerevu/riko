# Authoritative Riko CLI Implementation Gameplan

## 1. Mission

Create a separate `riko-cli` package that provides one coherent command-line interface for the Riko ecosystem without becoming another application monolith.

The CLI must support:

1. Inspecting installed Riko modules, export targets, and plugins.
2. Validating, describing, and running Riko pipelines.
3. Discovering and executing MCP and OpenAPI capabilities.
4. Running AI inference, capability selection, planning, verification, summarization, and research.
5. Building and reviewing Riko sites.
6. Running stateful AI conversations.
7. Running reproducible noninteractive workflows.
8. Inspecting plans, artifacts, manifests, approvals, and execution history.
9. Providing an optional non-AI command shell.
10. Loading package-specific commands through entry points.

The CLI owns:

* argument parsing;
* command discovery;
* configuration assembly;
* `ExecutionContext` construction;
* terminal interaction;
* approval prompts;
* output formatting;
* progress and event rendering;
* stable exit codes.

The CLI must not own:

* Riko execution internals;
* MCP sessions or HTTP clients;
* OpenAPI parsing;
* model provider logic;
* AI selection or planning;
* site generation;
* conversation reasoning;
* artifact storage implementations.

---

# 2. Package and repository

Create:

```text
nerevu/riko-cli
```

Python package:

```text
riko_cli
```

Console entry point:

```toml
[project.scripts]
riko = "riko_cli.__main__:main"
```

Suggested installation:

```bash
pip install riko-cli
```

Optional integrations:

```bash
pip install "riko-cli[mcp]"
pip install "riko-cli[ai]"
pip install "riko-cli[site]"
pip install "riko-cli[chat]"
pip install "riko-cli[all]"
```

Packages installed independently should also be discovered automatically:

```bash
pip install riko-cli riko-mcp riko-ai riko-site
```

---

# 3. Prerequisites

The first functional CLI release should assume these public service layers exist.

## Riko

* AnyIO execution is complete.
* One-shot pipeline lifecycle is stable.
* Module and export registries are available.
* Pipeline validation and execution have reusable Python APIs.
* `ExecutionContext` supports resources, cancellation, deadlines, metadata, and events.

## `riko-mcp`

At minimum:

* capability domain types;
* capability catalogs;
* MCP stdio client;
* plan validation;
* static MCP execution;
* APIs.guru and OpenAPI inspection services.

## `riko-ai`

At minimum:

* provider-neutral inference;
* model profiles;
* `infer`;
* capability selection contracts;
* conversation runner contracts.

## `riko-site`

At minimum:

* `SiteArtifact`;
* `SiteSpec`;
* site validation;
* at least one exporter.

The CLI may be scaffolded earlier, but package commands must not duplicate missing service-layer behavior.

---

# 4. Architectural rule

The CLI is an adapter over reusable application services.

Correct:

```python
async def plan_command(
    args: ApiPlanArgs,
    *,
    context: CliContext,
) -> CommandResult:
    request = ApiPlanRequest(
        task=args.task,
        allow_discovery=args.allow_discovery,
    )

    outcome = await context.services.capabilities.plan(
        request,
        execution=context.execution,
    )

    return CommandResult(data=outcome)
```

Incorrect:

```python
async def plan_command(args):
    # Fetch APIs.guru.
    # Rank APIs.
    # Parse OpenAPI.
    # Call the model.
    # Execute HTTP.
    ...
```

Every substantial command operation must also be callable:

* from Python;
* from an MCP server;
* from a web service;
* from a notebook;
* from tests;
* from scheduled automation.

---

# 5. Base implementation choices

## 5.1 Argument parsing

Use the `Click` package.

Reasons:

* already used by other riko packages
* nested subcommands are sufficient;
* command plugins can register parsers;
* stable behavior across Python 3.12+;

Do not pass `argparse.Namespace` into domain services.

Convert parsed arguments into typed request objects at the command adapter boundary.

## 5.2 Configuration parsing

Use:

```text
tomllib
pathlib
os.environ
```

Do not require a configuration framework.

## 5.3 Async entry point

There must be one top-level AnyIO boundary:

```python
def main() -> int:
    return anyio.run(main_async)
```

Do not call:

```python
asyncio.run(...)
anyio.run(...)
```

inside commands or service adapters.

## 5.4 Optional terminal enhancements

Base CLI must function with the standard library.

Optional extras may provide:

```text
rich
    enhanced tables, syntax display, progress, and color

prompt-toolkit
    history, completion, multiline input, and richer chat input

argcomplete
    generated shell completion
```

No optional renderer may change the data or exit-code contract.

---

# 6. Command plugin system

Packages register command providers through entry points.

```toml
[project.entry-points."riko.commands"]
mcp = "riko_mcp.cli:provider"
ai = "riko_ai.cli:provider"
site = "riko_site.cli:provider"
```

Built-in commands use the same protocol internally.

## 6.1 Command provider

```python
class CommandProvider(Protocol):
    name: str
    distribution: str
    api_version: int

    def commands(self) -> tuple["CommandSpec", ...]:
        ...
```

Initial API version:

```text
1
```

## 6.2 Command specification

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CommandSpec:
    path: tuple[str, ...]
    help: str

    configure: Callable[
        [argparse.ArgumentParser],
        None,
    ]

    handler: AsyncCommandHandler

    description: str | None = None
    aliases: tuple[tuple[str, ...], ...] = ()

    hidden: bool = False
    experimental: bool = False
```

Example path:

```python
("capabilities", "list")
```

corresponds to:

```bash
riko capabilities list
```

## 6.3 Collision policy

Command paths must be unique.

On collision:

* fail during registry construction;
* identify both distributions;
* identify the conflicting command path;
* do not silently prefer installation order.

Runtime test registration may support:

```python
replace=True
```

Installed entry-point plugins may not replace built-in commands by default.

## 6.4 Lazy imports

Plugin CLI modules must remain lightweight.

Running:

```bash
riko --help
```

must not eagerly import:

* model SDKs;
* MCP SDK transports;
* Django;
* Pelican;
* Lektor;
* database clients.

A command handler may import its optional runtime dependency only when invoked.

---

# 7. CLI application context

```python
@dataclass(slots=True, kw_only=True)
class CliContext:
    execution: ExecutionContext

    output: OutputWriter
    events: CliEventSink
    prompts: PromptService

    configuration: CliConfiguration
    project: ProjectContext

    services: ServiceRegistry
```

## 7.1 Project context

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectContext:
    root: Path
    working_directory: Path
    riko_directory: Path
```

Project detection should walk upward from the working directory and prefer the nearest directory containing one of:

```text
.riko/
pyproject.toml
.git/
```

Explicit override:

```bash
riko --project /path/to/project ...
```

Do not silently change the process working directory.

---

# 8. Configuration precedence

Use this precedence:

```text
package defaults
→ user configuration
→ project configuration
→ explicit --config files, in order
→ environment variables
→ command-line arguments
```

Suggested locations:

```text
User
    $XDG_CONFIG_HOME/riko/config.toml
    ~/.config/riko/config.toml

Project
    .riko/config.toml
```

Explicit files:

```bash
riko --config team.toml --config local.toml ...
```

Later files replace earlier scalar values.

Package-specific configuration is delegated to the owning package:

```text
.riko/mcp.toml
.riko/ai.toml
.riko/site.toml
```

The CLI builds the final runtime configuration and injects package resources into `ExecutionContext`.

## 8.1 No secret serialization

Resolved secrets must never appear in:

* `riko config show`;
* debug dumps;
* tracebacks;
* JSON output;
* plans;
* command history;
* conversation exports.

Configuration display uses redacted placeholders:

```text
GITHUB_TOKEN = "<redacted>"
```

## 8.2 Configuration inspection

Commands:

```bash
riko config paths
riko config show
riko config validate
```

Useful options:

```bash
riko config show --sources
riko config show --format json
```

`--sources` should show where each non-secret value originated.

---

# 9. Global command options

Keep global options limited and stable.

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

Default output format:

```text
human
```

Automation formats:

```text
json
jsonl
raw
```

Optional later format:

```text
yaml
```

Do not require YAML support in the base installation.

---

# 10. Output contract

## 10.1 Standard streams

```text
stdout
    primary command output

stderr
    logs, progress, warnings, prompts, diagnostics
```

In JSON mode, stdout must contain only valid JSON or JSON Lines.

Decorative text must never be mixed into machine-readable stdout.

## 10.2 Command result

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CommandResult:
    data: JsonValue | None = None
    summary: str | None = None

    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, JsonValue] = field(
        default_factory=dict
    )

    exit_code: int = 0
```

Handlers return domain-derived data, not already-formatted terminal strings.

## 10.3 Serialization

Support:

* dataclasses;
* enums;
* paths;
* datetimes;
* decimals;
* mappings;
* sequences;
* public `to_json()` protocols.

Serialization must be deterministic.

Unknown objects should cause a structured serialization error rather than fall back to `repr()` in JSON mode.

## 10.4 Human rendering

Human format may use:

* headings;
* concise tables;
* syntax-highlighted JSON;
* status messages;
* progress indicators.

Human rendering must still work without Rich.

---

# 11. Event rendering

Long-running services communicate through structured events.

```python
type CliEvent = (
    ProgressStarted
    | ProgressUpdated
    | ProgressCompleted
    | WarningRaised
    | ArtifactCreated
    | ApprovalRequested
    | ExecutionStarted
    | ExecutionCompleted
    | ConversationEvent
    | SiteBuildEvent
)
```

The CLI installs an event sink into `ExecutionContext`.

```python
execution = ExecutionContext(
    event_sink=cli_event_sink,
    ...
)
```

## Human mode

Render progress interactively when stderr is a terminal.

## JSONL mode

Emit one event per line:

```json
{"type":"execution_started","capabilityId":"..."}
{"type":"execution_completed","status":"succeeded"}
```

## Noninteractive mode

Do not render animated progress.

Use simple stderr messages or JSONL events.

---

# 12. Error and exit-code contract

Use stable exit codes.

```text
0
    success

1
    unexpected internal failure

2
    command usage or configuration error

3
    validation failure

4
    approval required or denied

5
    execution failure

6
    partial success

7
    missing plugin or optional dependency

8
    unavailable external service

9
    budget or policy rejection

130
    interrupted by user
```

## Structured error

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CliErrorResult:
    code: str
    message: str

    details: JsonValue | None
    exit_code: int

    retryable: bool = False
```

JSON output:

```json
{
  "ok": false,
  "error": {
    "code": "approval_required",
    "message": "Execution requires confirmation.",
    "details": {
      "capabilityId": "..."
    }
  }
}
```

Default human errors should be concise.

`--trace` includes the traceback on stderr.

Secrets must be redacted before rendering either form.

---

# 13. Interactive approval provider

`riko-cli` supplies an approval-provider implementation to `riko-mcp` and other services.

```python
class PromptService(Protocol):
    async def approve(
        self,
        request: ApprovalRequest,
    ) -> ApprovalDecision:
        ...
```

## 13.1 Approval presentation

Display:

* capability or operation;
* origin;
* server or destination host;
* arguments with secrets redacted;
* read/write/destructive effects;
* schema fingerprint;
* plan rationale;
* expected output shape.

Example:

```text
Approval required

Capability:
    Exchange-rate latest values

Origin:
    OpenAPI operation

Method:
    GET

Host:
    api.example.org

Arguments:
    base = USD
    symbols = GBP

Effects:
    read-only
    open-world

Approve once? [y/N]
```

## 13.2 `--yes`

`--yes` automatically confirms actions that are already permitted by the active execution policy.

It must not independently enable:

* destructive operations;
* private-network access;
* a denied host;
* missing credentials;
* an invalid plan.

A destructive operation requires both:

```text
explicit policy permission
and
confirmation or an explicit unattended-execution setting
```

## 13.3 `--no-input`

When interaction is disabled and confirmation is required:

* do not hang;
* do not assume approval;
* return exit code `4`;
* emit a structured `approval_required` error.

## 13.4 Approval scope

Initial scopes:

```python
class ApprovalScope(StrEnum):
    ONCE = "once"
    CONVERSATION = "conversation"
```

Persistent approvals remain an owning-package feature, not generic CLI state.

---

# 14. Built-in command tree

## 14.1 General commands

```text
riko version
riko help
riko commands list
riko plugins list
riko plugins inspect NAME
riko config paths
riko config show
riko config validate
```

## 14.2 Module commands

```text
riko modules list
riko modules describe NAME
riko modules schema NAME
```

## 14.3 Export commands

```text
riko exports list
riko exports describe NAME
```

## 14.4 Pipeline commands

```text
riko pipeline validate FILE
riko pipeline describe FILE
riko pipeline run FILE
```

Options:

```text
--input PATH
--output PATH
--set KEY=VALUE
--deadline SECONDS
--dry-run
```

`pipeline describe` should support Riko execution modes such as:

```text
describe
describe inputs
describe dependencies
```

without running the pipeline.

## 14.5 Artifact commands

Generic artifact inspection may be built into `riko-cli`:

```text
riko artifacts inspect URI
riko artifacts copy URI PATH
riko artifacts hash URI
```

Domain-specific artifact operations remain package commands.

---

# 15. `riko-mcp` command plugin

Registered by `riko-mcp`.

## MCP servers

```text
riko mcp servers
riko mcp inspect SERVER
riko mcp tools SERVER
riko mcp resources SERVER
riko mcp prompts SERVER
riko mcp refresh SERVER
```

## Direct MCP execution

```text
riko mcp call SERVER TOOL
riko mcp read SERVER URI
```

Arguments may be supplied as:

```bash
--arg key=value
--arguments request.json
--stdin
```

## Unified capabilities

```text
riko capabilities list
riko capabilities search QUERY
riko capabilities inspect ID
riko capabilities refresh
riko capabilities execute PLAN
riko capabilities history
```

## API and OpenAPI commands

```text
riko api search QUERY
riko api candidates QUERY
riko api schemas QUERY --top 5
riko api inspect-schema ID
riko api operations SCHEMA_ID
riko api normalize FILE
riko api execute PLAN
```

Examples:

```bash
riko api search "currency exchange"
```

```bash
riko api schemas \
    "currency exchange" \
    --top 5 \
    --output schemas.json
```

```bash
riko api normalize openapi.json \
    --output capabilities.json
```

The CLI does not generate Python functions from OpenAPI operations.

---

# 16. `riko-ai` command plugin

Registered by `riko-ai`.

## Inference

```text
riko ai infer
riko ai summarize
riko ai verify
riko ai research
```

Example:

```bash
riko ai infer \
    --instruction "Summarize in two sentences" \
    --input article.txt
```

## Capability selection

```text
riko ai select
```

Example:

```bash
riko ai select \
    --task "Convert 100 USD to GBP" \
    --allow-discovery \
    --output plan.json
```

This creates a plan. It does not execute unless explicitly requested through a separate command.

## Planning

```text
riko ai plan
riko ai plan validate FILE
riko ai plan execute FILE
```

Planning and execution remain separate even when surfaced in one command group.

## Profiles

```text
riko ai profiles list
riko ai profiles show NAME
riko ai profiles validate FILE
```

## Evaluations

```text
riko ai evaluate FILE
riko ai evaluation show RUN_ID
riko ai evaluation compare RUN_A RUN_B
```

---

# 17. Workflow commands

A workflow is a reproducible declarative execution document.

```text
riko workflow validate FILE
riko workflow describe FILE
riko workflow run FILE
```

Example:

```yaml
version: 1

profile: api-capability-selector

task: Convert 100 USD to GBP.

input:
  amount: 100
  source_currency: USD
  target_currency: GBP

selection:
  allow_discovery: true
  discovery_providers:
    - apis_guru

execution:
  approval: policy

output:
  format: json
```

## Pipeline versus workflow

```text
pipeline
    deterministic Riko stage definition

workflow
    may include AI selection, discovery,
    planning, verification, and approval
```

Commands remain distinct:

```bash
riko pipeline run pipeline.toml
riko workflow run workflow.yaml
```

## Service ownership

* static pipeline schema: Riko;
* AI workflow schema: `riko-ai`;
* capability execution: `riko-mcp`;
* command dispatch: `riko-cli`.

---

# 18. Conversation CLI

## 18.1 Ownership

```text
riko-ai
    conversation model
    runner
    memory
    persistence protocols
    planning
    model turns

riko-mcp
    validated capability execution

riko-cli
    terminal input
    event display
    approval prompts
    conversation commands
```

The conversation engine is not implemented inside `riko-cli`.

## 18.2 Commands

Start a conversation:

```bash
riko chat
```

Use a profile:

```bash
riko chat --profile technical-researcher
```

Resume:

```bash
riko chat --resume CONVERSATION_ID
```

Management:

```text
riko chat list
riko chat show CONVERSATION_ID
riko chat export CONVERSATION_ID
riko chat delete CONVERSATION_ID
```

Noninteractive:

```bash
riko chat run \
    --profile api-capability-selector \
    --message "Convert 100 USD to GBP" \
    --format json \
    --no-input
```

Scripted turns:

```bash
riko chat run conversation.yaml
```

## 18.3 Conversation persistence

Default:

```text
SQLite
```

Suggested path:

```text
$XDG_DATA_HOME/riko/conversations.db
```

Project-local override:

```bash
riko chat --store .riko/conversations.db
```

Implementations owned by `riko-ai`:

```text
InMemoryConversationStore
JsonlConversationStore
SqliteConversationStore
PostgresConversationStore
```

The CLI only selects and configures the store.

## 18.4 Conversation events

The conversation runner emits:

```text
MessageStarted
ContentDelta
CapabilityProposed
ApprovalRequested
CapabilityStarted
CapabilityCompleted
ArtifactCreated
TurnCompleted
ConversationFailed
```

The CLI renders these events.

It must not consume provider-specific streaming objects.

## 18.5 Conversation memory display

Commands:

```text
riko chat memory CONVERSATION_ID
riko chat artifacts CONVERSATION_ID
riko chat plan CONVERSATION_ID
```

The CLI displays:

* current objective;
* conversation summary;
* pinned facts;
* recent turns;
* active plan;
* referenced artifacts.

It does not regenerate memory itself.

## 18.6 Conversation commands

Initial slash commands:

```text
/help
/status
/artifacts
/plan
/approve
/deny
/save-workflow PATH
/clear
/exit
```

Slash commands are terminal controls, not messages sent to the model.

## 18.7 Workflow extraction

```text
/save-workflow currency-conversion.yaml
```

May serialize:

* profile;
* objective;
* explicit inputs;
* selected capabilities;
* plan steps;
* approval requirements;
* output bindings.

Must not serialize:

* credentials;
* hidden model reasoning;
* transient session IDs;
* conversation-only approval grants.

---

# 19. Site command plugin

Registered by `riko-site`.

```text
riko site validate
riko site assemble
riko site build
riko site preview
riko site serve
riko site inspect-route PATH
riko site drafts
riko site approve REVIEW_ID
riko site reject REVIEW_ID
riko site manifest
```

Examples:

```bash
riko site build \
    --renderer mithril \
    --profile wei \
    --output wei-app/app
```

```bash
riko site build \
    --renderer html \
    --engine htpy \
    --output dist
```

```bash
riko site drafts --format json
```

`site serve` may run a lightweight preview server, but the server implementation belongs to `riko-site`.

---

# 20. Non-AI command shell

Provide later:

```bash
riko shell
```

Purpose:

* inspect modules;
* inspect catalogs;
* inspect plans;
* execute explicit commands;
* inspect artifacts;
* run pipelines.

Example:

```text
riko> modules list
riko> capabilities search exchange rate
riko> api schemas "exchange rate" --top 5
riko> capabilities inspect openapi:example:get-latest
riko> exit
```

## Reuse the command registry

The shell parses input with `shlex` and dispatches through the same command registry as ordinary invocations.

Do not implement a second command system.

## Security

Do not initially support:

```text
!shell-command
```

or arbitrary OS shell escape.

The shell is a Riko command workbench, not a system shell.

---

# 21. Old CLI monolith migration

The old command harness combined configurable agents, multiple model providers, retrieval, web tools, OpenAPI conversion, API discovery, and scenario execution.

Its responsibilities map as follows:

| Old responsibility             | New owner and command              |
| ------------------------------ | ---------------------------------- |
| Build agent teams              | `riko-ai` workflow profiles        |
| Interactive agent conversation | `riko chat`                        |
| Run declarative scenarios      | `riko ai evaluate`                 |
| Provider selection             | `riko-ai` model registry           |
| Cost/performance optimization  | `riko-ai` model routing            |
| Web search and scraping        | selected Riko/MCP capabilities     |
| APIs.guru discovery            | `riko api search`                  |
| Download OpenAPI schema        | `riko api schemas`                 |
| OpenAPI-to-function conversion | replaced by operation capabilities |
| Execute selected API           | `riko capabilities execute`        |
| Query vector storage           | `riko-ai` semantic index           |
| Oversized result storage       | `riko-mcp` artifacts               |
| Direct Python REPL             | sandboxed MCP capability           |
| Multi-agent supervision        | bounded `TaskPlan`                 |
| Agent scenario files           | workflow and evaluation files      |
| Terminal parsing and output    | `riko-cli`                         |

The old `convert-schemas` command becomes:

```bash
riko api normalize openapi.json \
    --output capabilities.json
```

The old `build-agents` workflow becomes one of:

```bash
riko chat --profile PROFILE
```

```bash
riko workflow run workflow.yaml
```

The old scenario runner becomes:

```bash
riko ai evaluate scenarios.yaml
```

---

# 22. Logging and diagnostics

## Levels

```text
ERROR
WARNING
INFO
DEBUG
TRACE
```

Map:

```text
default
    WARNING

-v
    INFO

-vv
    DEBUG

--trace
    traceback and detailed diagnostics
```

## Logging output

Logs go to stderr.

JSON log mode:

```bash
riko --log-format json ...
```

Every log record should include, where available:

```text
run_id
conversation_id
pipeline
command
capability_id
server
phase
```

## Diagnostic command

```bash
riko doctor
```

It should inspect:

* Python version;
* Riko version;
* installed command plugins;
* plugin API compatibility;
* optional dependencies;
* configuration syntax;
* project detection;
* writable data/cache directories;
* MCP command availability;
* model provider configuration, without showing keys.

`doctor` should not make external network calls unless:

```bash
riko doctor --network
```

is explicitly supplied.

---

# 23. Cache and data directories

Suggested directories:

```text
Configuration
    $XDG_CONFIG_HOME/riko/

Data
    $XDG_DATA_HOME/riko/

Cache
    $XDG_CACHE_HOME/riko/

State
    $XDG_STATE_HOME/riko/
```

Project-local state:

```text
.riko/
├── config.toml
├── mcp.toml
├── ai.toml
├── site.toml
├── approvals.json
├── artifacts/
├── cache/
└── state/
```

The CLI should use a small platform-path utility that supports Linux, macOS, and Windows.

It may use `platformdirs` if cross-platform behavior would otherwise become error-prone. This is an acceptable small base dependency.

---

# 24. Security rules

The CLI must not:

* evaluate Python supplied in command arguments;
* execute arbitrary shell commands;
* accept model-generated subprocess commands;
* print secrets;
* place secrets into shell history;
* automatically approve destructive operations;
* execute a plan that has not been revalidated;
* follow an OpenAPI URL selected directly by a model;
* enable private-network calls through `--yes`;
* weaken package policy through output-format flags.

## Sensitive arguments

Prefer credential references:

```bash
--credential exchange_api
```

over:

```bash
--api-key secret-value
```

When direct sensitive input is unavoidable, support:

```text
environment variables
stdin
terminal secret prompt
secret-provider references
```

Avoid command-line secrets because process listings and shell history may expose them.

---

# 25. Proposed repository layout

```text
riko_cli/
├── __init__.py
├── __main__.py
├── py.typed
│
├── app.py
├── context.py
├── exceptions.py
├── exit_codes.py
│
├── commands/
│   ├── registry.py
│   ├── provider.py
│   ├── specification.py
│   │
│   ├── builtin/
│   │   ├── version.py
│   │   ├── help.py
│   │   ├── commands.py
│   │   ├── plugins.py
│   │   ├── config.py
│   │   ├── doctor.py
│   │   ├── modules.py
│   │   ├── exports.py
│   │   ├── pipeline.py
│   │   └── artifacts.py
│   │
│   ├── chat/
│   │   ├── command.py
│   │   ├── loop.py
│   │   ├── slash.py
│   │   ├── rendering.py
│   │   └── approvals.py
│   │
│   └── shell/
│       ├── command.py
│       ├── parser.py
│       └── loop.py
│
├── config/
│   ├── paths.py
│   ├── loading.py
│   ├── merging.py
│   ├── environment.py
│   ├── redaction.py
│   └── validation.py
│
├── output/
│   ├── protocol.py
│   ├── serialization.py
│   ├── human.py
│   ├── json.py
│   ├── jsonl.py
│   ├── raw.py
│   └── tables.py
│
├── events/
│   ├── sink.py
│   ├── rendering.py
│   └── progress.py
│
├── prompts/
│   ├── protocol.py
│   ├── approval.py
│   ├── secrets.py
│   └── noninteractive.py
│
├── services/
│   ├── registry.py
│   └── loading.py
│
└── testing/
    ├── runner.py
    ├── fake_provider.py
    └── snapshots.py
```

Package-specific command implementations remain in their packages:

```text
riko_mcp/cli/
riko_ai/cli/
riko_site/cli/
```

---

# 26. Implementation phases

## C0 — Architecture and command inventory

### Tasks

1. Inspect current Riko console entry points.
2. Inventory commands from Langly and AutoGen.
3. Inventory planned Riko, MCP, AI, and site services.
4. Write architecture records for:

   * thin CLI boundary;
   * command plugin protocol;
   * configuration precedence;
   * output and exit-code contracts;
   * interactive approval;
   * chat versus workflow versus shell.

### Acceptance criteria

* No production command behavior yet.
* Every old command has a documented destination.
* No business logic is assigned to `riko-cli`.

---

## C1 — CLI application and command registry

### Tasks

1. Create `riko-cli`.
2. Add the `riko` console script.
3. Implement `CommandProvider`.
4. Implement `CommandSpec`.
5. Implement nested command registration.
6. Implement collision detection.
7. Implement plugin API-version validation.
8. Add lightweight entry-point loading.
9. Add:

   * `riko version`;
   * `riko commands list`;
   * `riko plugins list`;
   * root help.

### Acceptance criteria

* Third-party test plugins can add nested commands.
* Collisions fail clearly.
* `riko --help` works without optional packages.
* Base CLI startup is fast and deterministic.

---

## C2 — Configuration and project context

### Tasks

1. Implement user/project/explicit config loading.
2. Implement environment interpolation.
3. Implement typed global options.
4. Implement project-root detection.
5. Implement redaction.
6. Implement:

   * `riko config paths`;
   * `riko config show`;
   * `riko config validate`.
7. Build `ExecutionContext` from resolved configuration.

### Acceptance criteria

* Precedence is tested.
* Context values override file values as intended.
* No secret appears in output or errors.
* Project detection is deterministic.

---

## C3 — Output, events, errors, and prompts

### Tasks

1. Implement human, JSON, JSONL, and raw output.
2. Implement `CommandResult`.
3. Implement structured errors.
4. Implement stable exit codes.
5. Implement event sink and progress rendering.
6. Implement interactive and noninteractive prompt services.
7. Implement approval display.
8. Implement `--yes`, `--no-input`, and `--dry-run`.

### Acceptance criteria

* JSON stdout is always parseable.
* Logs remain on stderr.
* Approval-required noninteractive commands fail immediately.
* Ctrl-C returns exit code `130`.
* Errors are redacted.

---

## C4 — Core Riko commands

### Tasks

1. Implement module inspection.
2. Implement export-target inspection.
3. Implement pipeline validation.
4. Implement pipeline description.
5. Implement pipeline execution.
6. Implement generic artifact inspection.
7. Add `riko doctor`.

### Acceptance criteria

* Commands use only supported Riko public APIs.
* Validation does not execute the pipeline.
* Pipeline output works in every output format.
* Missing optional integrations produce exit code `7`.

---

## C5 — MCP and capability commands

Implemented primarily in `riko-mcp`.

### Tasks

1. Register MCP server inspection commands.
2. Register capability catalog commands.
3. Register APIs.guru commands.
4. Register OpenAPI inspection commands.
5. Register explicit plan execution.
6. Support argument files and stdin.
7. Integrate approval provider.
8. Integrate artifact and telemetry display.

### Acceptance criteria

* Known MCP tools can be called without AI.
* APIs can be inspected without execution.
* Plans can be generated, saved, inspected, and separately executed.
* Destination hosts and effects are shown before approval.

---

## C6 — Base AI and workflow commands

Implemented primarily in `riko-ai`.

### Tasks

1. Register inference.
2. Register summarization.
3. Register verification.
4. Register capability selection.
5. Register planning.
6. Register workflow validation and execution.
7. Register profile inspection.
8. Register evaluation commands.

### Acceptance criteria

* Selection does not execute implicitly.
* Plans remain serializable.
* Workflow runs are reproducible.
* AI budgets and usage appear in output.

---

## C7 — Conversation CLI

### Tasks

1. Integrate `ConversationRunner`.
2. Implement line-oriented chat.
3. Render streaming conversation events.
4. Implement approval prompts.
5. Implement SQLite store selection.
6. Implement resume/list/show/export/delete.
7. Implement slash commands.
8. Implement artifact and plan inspection.
9. Implement workflow extraction.
10. Implement noninteractive conversation runs.

### Acceptance criteria

* Conversation business logic remains in `riko-ai`.
* Tool execution remains in `riko-mcp`.
* Conversation resume preserves state.
* Large tool results appear as artifact previews.
* JSON noninteractive output is deterministic.
* Conversation-only approvals do not leak into later conversations.

---

## C8 — Site commands

Implemented primarily in `riko-site`.

### Tasks

1. Register validate, assemble, build, and preview.
2. Register route and manifest inspection.
3. Register draft review commands.
4. Render build events.
5. Support Mithril, htpy, and later exporters.
6. Integrate JSON approval store updates.

### Acceptance criteria

* Site commands call reusable `riko-site` services.
* Draft approval uses content hashes.
* Production and preview policies remain distinct.
* Build results are machine-readable.

---

## C9 — Non-AI shell

### Tasks

1. Implement line parser with `shlex`.
2. Dispatch through the existing command registry.
3. Add command history.
4. Add basic completion when optional support exists.
5. Add safe shell commands:

   * help;
   * history;
   * exit.
6. Do not add OS shell escape.

### Acceptance criteria

* Shell commands behave identically to one-shot commands.
* No second command implementation exists.
* The shell does not require `riko-ai`.

---

## C10 — Documentation and completion

### Tasks

1. Generate command reference from registry metadata.
2. Generate shell completion where supported.
3. Add example configurations.
4. Add example pipelines and workflows.
5. Document exit codes.
6. Document JSON output contracts.
7. Document plugin authoring.

### Acceptance criteria

* Command docs are generated, not manually duplicated.
* Plugin developers can add a command without editing `riko-cli`.
* Automation users have stable schemas.

---

## C11 — Optional rich TUI

Only after the line-oriented CLI is stable.

Possible package:

```text
nerevu/riko-chat
```

or extra:

```text
riko-cli[tui]
```

Features may include:

* conversation panes;
* plan viewer;
* artifact viewer;
* schema browser;
* approval forms;
* build monitor;
* multiple sessions.

The TUI remains a frontend over the same service and event contracts.

---

# 27. Pull-request sequence

## `riko-cli`

1. `cli-architecture-and-command-registry`
2. `cli-config-and-project-context`
3. `cli-output-events-and-errors`
4. `cli-core-riko-commands`
5. `cli-chat-adapter`
6. `cli-shell`
7. `cli-docs-and-completion`

## `riko-mcp`

1. `cli-mcp-inspection`
2. `cli-capability-catalog`
3. `cli-openapi-discovery`
4. `cli-capability-execution`

## `riko-ai`

1. `cli-infer-and-models`
2. `cli-capability-selection`
3. `cli-workflows`
4. `cli-conversations`
5. `cli-evaluations`

## `riko-site`

1. `cli-site-build`
2. `cli-site-review`
3. `cli-site-exporters`

Do not combine CLI adapters with unrelated domain refactors.

---

# 28. Testing strategy

## Unit tests

Cover:

* command registration;
* nested parsing;
* command collisions;
* API-version mismatch;
* configuration precedence;
* project detection;
* redaction;
* serialization;
* exit codes;
* noninteractive prompts;
* approval scopes.

## CLI integration tests

Invoke the actual console entry point in subprocesses.

Test:

```text
riko --help
riko version
riko commands list
riko modules list
riko pipeline validate
riko config show
```

Assertions:

* stdout;
* stderr;
* exit code;
* JSON validity;
* secret redaction.

## Plugin fixtures

Provide fake command distributions for:

* valid plugin;
* duplicate command;
* incompatible API version;
* missing optional dependency;
* failing handler.

## Conversation tests

Use:

* deterministic fake AI provider;
* fake conversation store;
* fake MCP capability executor;
* approval-required tool;
* oversized artifact result;
* interrupted streaming turn.

## Terminal tests

Test:

* TTY and non-TTY behavior;
* color auto-detection;
* no progress animation when redirected;
* Ctrl-C;
* EOF;
* multiline input where supported.

## Snapshot tests

Use snapshots for:

* root help;
* nested help;
* human tables;
* structured errors;
* approval prompts;
* conversation transcripts.

Do not snapshot secrets, timestamps, random IDs, or terminal-width-dependent wrapping without normalization.

---

# 29. Performance requirements

Measure:

* base CLI startup;
* `riko --help`;
* plugin discovery;
* configuration loading;
* command dispatch.

Initial targets:

```text
riko --help
    under 250 ms on a typical development machine,
    excluding cold Python startup variability

No optional provider SDK imported for root help

No network calls during help, version,
commands list, or config show
```

Plugin discovery may be cached per process but should not require persistent cache initially.

---

# 30. Explicit non-goals

Do not implement in the initial CLI:

* domain business logic;
* a required Rich dependency;
* a required Prompt Toolkit dependency;
* a required YAML dependency;
* arbitrary shell execution;
* in-process Python evaluation;
* autonomous destructive approval;
* hidden conversation memory;
* credential storage;
* model-provider SDK objects in command results;
* a second workflow engine;
* a second plugin registry for each package;
* a full-screen TUI before the line interface is stable;
* remote daemon management;
* distributed conversation coordination.

---

# 31. Initial Claude Code prompt

```text
You are implementing Phase C0 and Phase C1 of the authoritative
Riko CLI roadmap.

Repositories:
- nerevu/riko, most current branch
- nerevu/langly, latest reachable snapshot
- nerevu/autogen, latest reachable snapshot
- new repository nerevu/riko-cli

Assumptions:
- Riko’s AnyIO migration and public execution services exist,
  or may be represented by temporary test fixtures.
- riko-cli must remain a thin adapter.
- Use argparse and tomllib.
- Do not add Click or Typer.
- Do not add MCP, AI, site, or conversation business logic.
- Optional package commands will use the riko.commands entry-point group.

Execute only:

C0
    architecture and command inventory

C1
    CLI application and command registry

Required work:

1. Inspect existing Riko console entry points and public APIs.
2. Inspect the latest Langly and AutoGen command surfaces.
3. Produce a migration matrix for every old command.
4. Create the riko-cli package.
5. Add the `riko` console entry point.
6. Implement:
   - CommandProvider
   - CommandSpec
   - command registry
   - nested argparse registration
   - entry-point discovery
   - plugin API-version validation
   - command collision detection
7. Add built-in commands:
   - riko version
   - riko commands list
   - riko plugins list
8. Add root and nested help.
9. Ensure root help does not import optional heavy dependencies.
10. Add tests for:
    - valid plugin
    - nested command
    - duplicate command
    - incompatible API version
    - hidden command
    - experimental command
    - missing plugin dependency
11. Add architecture decision records.
12. Run Ruff, Pyright, and Pytest.
13. Stop after C1.

Before editing, report:

- repositories, branches, and commits inspected;
- existing entry points;
- old command inventory;
- files to add;
- command protocol design;
- compatibility hazards.

After editing, report:

- files changed;
- public CLI APIs;
- test commands and results;
- startup behavior;
- unresolved decisions.

Do not implement configuration merging, output formatting,
conversation handling, MCP execution, AI selection, site builds,
or the interactive shell in this phase.
```

---

# 31.1 Connector and orchestration plugin surface

Shelf-promoted integrations are exposed through command plugins. The base CLI does not
embed protocol libraries or run a scheduler daemon.

Suggested plugin commands:

```text
riko sources list
riko sources inspect URI
riko sources resolve URI
riko sources test URI

riko orchestration list
riko orchestration scaffold airflow NAME
riko orchestration scaffold prefect NAME
riko orchestration scaffold dagster NAME

riko sql inspect CONNECTION_REF
riko dbt run --select SELECTOR
```

Rules:

* `sources resolve` prints an immutable source plan and performs no network I/O unless
  `--probe` is supplied;
* machine-readable output follows the existing stdout contract;
* credentials are named references and remain redacted;
* protocol extras are imported only when their command is invoked;
* scaffolding emits files but does not silently deploy them;
* Airflow, Prefect, and Dagster plugins call reusable adapter services;
* the CLI may execute one pipeline run, but persistent scheduling belongs to the selected
  orchestrator or operating system;
* connector and orchestrator command collisions follow the existing entry-point policy.

A future `riko run --schedule ...` flag is explicitly rejected because it would turn the
CLI into another scheduler process.

# 32. Final architecture

```text
riko
    pipeline engine and execution contracts

riko-mcp
    external capability connectivity and execution

riko-ai
    inference, selection, planning, and conversation engine

riko-site
    site assembly, rendering, and publication

riko-cli
    batch CLI, conversation terminal, command shell,
    configuration assembly, prompts, and output rendering

riko-chat
    optional future full-screen TUI only
```

The critical rule is:

```text
The CLI coordinates packages.
It does not reimplement them.
```
