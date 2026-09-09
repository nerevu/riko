# Operations as Code gameplan

## 1. Mission

Define a Git-first, vendor-neutral model for **Operations as Code** built on the Riko
ecosystem: operational knowledge is versioned as code, resolved into inspectable plans,
executed through Riko pipelines and provider capabilities, verified against authoritative
systems, and kept independent of any one RMM, workflow SaaS, cloud console, or automation
UI.

The primary problem is operational lock-in. Scripts, runbooks, work plans, policies, and
automations often become trapped in systems such as an RMM or workflow platform. Teams then
maintain a second script repository, copy logic between products, or rewrite their
operational knowledge when they change vendors. Operations as Code makes the
version-controlled repository canonical and treats vendor-hosted copies as derived
deployments.

This plan exists to give those operational assets one reproducible, inspectable layer **above**
Riko Core without turning the Core pipeline engine into an RMM, control plane, scheduler, or
infrastructure-state manager.

This plan owns **operation-level reproducibility, source-of-truth semantics, planning,
import/normalization, deployment portability, compatibility reporting, and automation drift**.

Related authoritative plans:

* `execution-semantics.md` — immutable pipelines, execution, retry, state, identity,
  idempotency, cancellation, and error semantics;
* `extensibility.md` — versioned workflow serialization and extension/plugin registration;
* `connectors.md` — connector sessions, credential references, and secret resolution;
* `provider-integrations.md` — provider resources/actions, provider identity, provider-native
  operation-asset discovery/import/export/deployment hooks, webhooks, idempotent writes, and
  `OperationHandle` waiting;
* `mcp.md` — capability identity, schemas, effects, **capability discovery/catalog**, policy, and
  execution;
* `microsoft-administration.md` — Microsoft desired state, `ChangePlan`, approval,
  verification, evidence, and handoff semantics;
* `orchestration.md` — external scheduling, durable run boundaries, and runner adapters;
* `artifact-conversion.md` — durable artifacts, hashes, and artifact lineage;
* `cli.md` — command adapters, configuration, rendering, prompts, and exit codes;
* `commercialization.md` — commercial adoption/product strategy that consumes this architecture
  without defining its technical contracts.

## 2. Product and package boundary

Riko Core remains a **configurable pipeline engine for Python**. Operations as Code is an
ecosystem capability built on that engine, not a promise that the `riko` package itself is a
hosted automation platform.

Suggested package boundary:

```text
nerevu/riko
    Pipeline / Context / execution semantics
    module and export registries
    ordinary record processing

nerevu/riko-ops
    OperationSpec and operation services
    repository/project loading
    operation planning and verification coordination
    import/normalization
    deployment/export
    compatibility and automation-drift analysis

provider packages
    source/target-specific importers and deployers
    capability implementations
    provider-native plan/verification adapters

riko-cli
    terminal adapters for the reusable services above
```

The package name is provisional. The architectural boundary is not: Core supplies the
execution primitives; the operations package supplies operational semantics.

Commercial uses such as MSP automation management, migration assessments, hosted collaboration,
private runners, operation packs, and vertical managed services are ecosystem opportunities. They
must not be described as Core guarantees merely because this gameplan enables them.

## 3. Architectural rule

The canonical path is:

```text
Git repository
    ↓
OperationSpec
    ↓
resolve inputs + environment + capabilities
    ↓
inspect authoritative current state where supported
    ↓
OperationPlan
    ↓
policy / approval
    ↓
apply through pipelines + capabilities
    ↓
verify authoritative state
    ↓
evidence + deployment metadata
```

Canonical operation lifecycle terminology is therefore:

```text
validate → plan → apply → verify
```

Policy/approval is a gate **between plan and apply**, not an additional synonym for an operation
phase. Use `execute` for Pipeline/capability execution where those owners use it; do not introduce
`execute` as a synonym for Operations as Code `apply`.

For vendor-hosted execution:

```text
Git OperationSpec
    ↓
compile/export/deploy
    ↓
SuperOps / RMM / Azure Automation / GitHub Actions / other runner
    ↓
observed deployed revision
```

The external platform is an execution or deployment target. It does not become the canonical
source merely because it stores a generated script or workflow copy.

## 4. Operation versus existing Riko concepts

Do not introduce a second pipeline graph or execution runtime.

```text
Module
    reusable processing or capability primitive

Pipeline
    immutable executable dataflow owned by Riko Core

Workflow
    generic serialized coordination model owned by extensibility/tooling contracts

Operation
    an operational profile that adds source-of-truth, planning, deployment,
    verification, provenance, and compatibility semantics around existing
    pipelines/workflows/capabilities
```

`OperationSpec` is therefore a semantic envelope over existing execution and workflow
contracts, not a competing DAG language.

Also distinguish these names explicitly:

```text
OperationSpec
    a versioned operational definition

OperationPlan
    a resolved, inspectable plan for one OperationSpec invocation

CapabilityPlan
    one validated capability invocation plan; owned by mcp.md

ChangePlan
    one Microsoft administrative desired-state plan; owned by microsoft-administration.md

OperationHandle
    one in-flight asynchronous provider job; owned by provider-integrations.md
```

An `OperationPlan` may reference/embed domain plans, but it does not replace them. Its fingerprint
must incorporate the identities/fingerprints of referenced `CapabilityPlan`/`ChangePlan` values and
other plan-bearing domain steps so a changed nested plan invalidates operation-level approval.

## 5. Operation specification

An operation definition must be serializable, inspectable, and safe to version in Git.
Conceptually it includes:

```text
id
schema/version
summary
inputs and defaults
required capabilities/resources
pipeline/workflow reference
preconditions
planning strategy
approval/policy requirements
verification rules
manual handoff rules
deployment metadata
```

The serialized representation should reuse or specialize the versioned workflow format from
`extensibility.md`; it must not create another generic graph schema.

An operation may be fully declarative, partially declarative, or intentionally opaque at an
execution step. Planning must report that distinction instead of fabricating a diff for an
imperative script whose effects cannot be known safely in advance.

Required capability resolution uses the shared `CapabilityCatalog`/discovery contract from
`mcp.md`. The operations package may request/filter capabilities for an operation, but it must not
create a second operation-specific capability catalog.

## 6. Git-first source of truth

The repository is the canonical authoring source for operation definitions and source
artifacts.

A project may contain, for example:

```text
operations/
    onboard-user/
        operation.yaml
        scripts/
            configure.ps1
        tests/
    offboard-user/
        operation.yaml
    provision-device/
        operation.yaml

environments/
    defaults.yaml
    clients/
        example.yaml

.riko/
    config.toml
```

Requirements:

* operation definitions are reviewable as ordinary text changes;
* source scripts remain files rather than pasted strings duplicated across vendor UIs;
* generated/vendor copies carry enough metadata to identify their source revision;
* raw credentials are never committed in operation definitions;
* a dirty working tree may be allowed for local development but must be reported in run
  metadata when reproducibility matters;
* Git is the primary expected VCS, but runtime semantics must not depend on GitHub as a
  hosted service.

## 7. Reproducibility identity

Operations as Code means reproducibility of the **definition and decision path**, not a false
guarantee that a changing remote system will always produce byte-identical results.

A reproducibility record should be able to identify, as applicable:

```text
operation ID + schema version
source revision / Git commit
operation content fingerprint
referenced script/artifact hashes
resolved non-secret inputs
environment/client overlay identity
Riko/package versions
provider/capability identities
resolved OperationPlan fingerprint
referenced domain-plan fingerprints
execution/run ID
```

Secret values are excluded. Credential **references** may be recorded when policy permits.

The canonical identity/fingerprint/idempotency primitives remain owned by
`execution-semantics.md`; this plan defines which operation-level inputs participate in the
reproducibility record.

## 8. Validate, plan, apply, and verify

Borrow the useful discipline of infrastructure-as-code systems without copying their entire
resource/state model.

```text
validate
→ plan
→ policy / approval
→ apply
→ verify
```

### Validate

Validate schema, references, required plugins/capabilities, parameter types, deployment
support, and obvious policy violations without mutating remote systems.

### Plan

Planning resolves the operation against the target environment and, where a provider exposes
authoritative discovery/desired-state semantics, calculates the smallest known change.

A plan may classify actions such as:

```text
no_change
create
update
delete
execute
wait
manual_handoff
opaque
unsupported
```

`execute` here is a **planned step classification** for an opaque/imperative action, not the name of
the operation lifecycle phase.

`opaque` is important: a PowerShell script may be perfectly valid to run while still being
impossible to diff safely before execution.

Domain plans remain authoritative in their domains. For example, a Microsoft `ChangePlan`
from `microsoft-administration.md` may be embedded/referenced by an operation plan rather
than reimplemented here. Capability planning/policy metadata remains owned by `mcp.md`.

### Apply

Apply executes the exact resolved `OperationPlan` through normal Riko pipelines/capabilities.
Where approval is required, approval binds to the exact plan fingerprint; a changed operation plan
or changed referenced domain plan requires fresh authorization.

Apply must not silently re-plan after approval. If authoritative drift invalidates the approved plan,
return a stale/replan-required outcome so the caller can run `plan` again and obtain any required new
approval.

### Verify

Verification re-reads authoritative state or evaluates declared postconditions. Successful
process exit alone is not sufficient proof when authoritative verification is available.

Provider-native verification and domain-specific final-state semantics remain owned by their
providers/domains; this layer assembles those outcomes into the operation result/evidence.

## 9. State model: do not clone Terraform state

Riko must not introduce a universal shadow database of every remote resource merely to mimic
Terraform.

Prefer:

```text
Git definition
+
live authoritative provider state
+
small explicit Riko execution/checkpoint state where required
+
deployment metadata/evidence
```

`execution-semantics.md` owns Riko state/checkpoint contracts. Provider-native IDs and
identity maps remain owned by `provider-integrations.md`.

An operation may persist the minimum metadata needed for idempotency, resume, deployment
comparison, or evidence, but this plan does not define a second generic `StateStore`.

## 10. Environment and client overlays

The same operation should be reusable across customers, tenants, environments, or sites
without copying its implementation.

Keep logic separate from resolved configuration:

```text
operation definition
+ organization defaults
+ client/environment overlay
+ runtime parameters
+ credential references
= resolved invocation
```

Precedence must be deterministic and inspectable. Configuration resolution should reuse the
project/configuration rules owned by the relevant CLI/workflow contracts rather than
inventing provider-specific merge behavior.

An MSP should be able to answer which operation version and overlay are intended for each
client without maintaining one edited script per tenant.

## 11. Deployment and execution targets

An operation may run directly through Riko or be exported/deployed to another execution
system when that is operationally preferable.

Potential target classes include:

```text
local/private Riko runner
cron or system scheduler
GitHub Actions
Azure Automation
RMM script library / automation engine
workflow platform
provider-native job runner
```

`orchestration.md` remains authoritative for scheduling and durable run boundaries.
Provider-specific import/export/deployment/inspection hooks and target capability facts belong in
`provider-integrations.md` and provider packages.

A deployment adapter should record at least:

```text
target identity
target object identity
source operation fingerprint/source revision
deployed artifact fingerprint
deployment time/result
round-trip or comparison capability
```

The adapter must not silently edit the canonical operation to fit the target. Any semantic
loss is surfaced through compatibility reporting.

## 12. Automation drift

Operations as Code introduces a second important kind of drift in addition to desired-state
configuration drift.

### Configuration drift

The live system differs from the desired operational state declared or implied by an
operation. Domain-specific desired-state plans, such as Microsoft administration, own the
actual comparison semantics.

### Automation deployment drift

A vendor-hosted derived automation no longer matches its Git source.

Example:

```text
Git operation       v1.8 / fingerprint A
SuperOps deployment v1.6 / fingerprint B
Action1 deployment  locally modified / fingerprint C
```

The operations layer owns comparison/reporting of source revision and deployed artifact
identity. Provider integrations own retrieving the target-specific deployment identity/fingerprint
facts.

The operations layer must distinguish:

```text
in_sync
outdated
modified_remotely
missing
unknown
unverifiable
```

Drift detection is read-only by default. Reconciliation is an explicit deployment/apply
operation subject to normal policy.

## 13. Import and migration

Migration is a first-class use case because operational intellectual property frequently
exists only inside proprietary platforms.

An importer may acquire:

```text
scripts
workflow definitions
automation steps
policies
monitors/remediation rules
scheduled jobs
runbooks
guidebooks
work plans
checklists
knowledge-base procedures
client-specific variables and mappings
```

The import path is:

```text
source platform / export
    ↓
acquire source artifacts
    ↓
inventory + classify
    ↓
normalize known semantics
    ↓
proposed OperationSpec + preserved source artifacts
    ↓
validate + human review where required
    ↓
compatibility analysis for target
```

Provider-specific discovery/acquisition/export hooks belong to `provider-integrations.md` and the
provider package. The operations package owns the common normalized import/provenance/lossiness and
compatibility model.

## 14. Import provenance and lossiness

Never discard the source representation merely because a normalized operation was produced.
Imported material should retain provenance such as:

```text
source provider/platform
source object type and stable ID when available
export/import timestamp
source content hash
original artifact reference
normalizer/importer version
normalization warnings
```

Normalization must report confidence/lossiness explicitly. Suggested classes:

```text
exact
portable_with_script
adaptation_required
manual_only
unsupported
unknown
```

AI may assist in interpreting scripts or prose, mapping vendor concepts, or proposing an
`OperationSpec`, but AI output is a proposal. Unknown equivalence must not be silently treated
as an exact mapping, and an AI proposal must pass normal validation/policy before it can be applied
or deployed.

## 15. RMM-to-RMM and platform migration

A migration assessment should be able to compare a normalized operation estate with a target
provider and report reuse potential before any mutation.

Conceptually:

```text
source estate
    ↓
normalized operations
    ↓
target capability catalog + provider compatibility facts
    ↓
CompatibilityReport
```

`mcp.md` owns the common capability catalog. `provider-integrations.md` owns target-specific facts
and mappings. This plan owns the cross-provider `CompatibilityReport` and its lossiness decision.

A report can summarize:

```text
fully portable
script portable
requires adaptation
requires manual replacement
unsupported
```

and retain per-operation reasons and missing capabilities.

This allows migrations such as RMM A → RMM B without making either RMM the canonical
automation repository. The long-term desired shape is:

```text
Git
└── Riko Operations
      ├── current RMM target
      ├── future RMM target
      ├── Microsoft/provider APIs
      └── private/cloud runners
```

Migration and automation portability are strategic adoption levers, not promises that arbitrary
vendor workflows can be translated losslessly.

## 16. Manual work is representable

Not every operation can or should be automated.

An imported work plan or runbook may contain manual handoffs, approvals, or steps that have
no safe target capability. Preserve them explicitly rather than dropping them or generating
unsafe automation.

An operation can therefore combine:

```text
automated pipeline/capability step
manual_handoff
approval
wait for provider operation
verification
```

The domain owning a handoff defines its specialized payload; Operations as Code owns only the
fact that the operation remains incomplete until the declared handoff contract is satisfied
or intentionally waived by policy.

## 17. Reusable operation packs

Operations should be reusable units analogous to modules/components in infrastructure-as-code
ecosystems, while extension registration remains owned by `extensibility.md`.

Examples might include:

```text
employee-onboarding
employee-offboarding
managed-device-baseline
autopilot-provisioning
m365-security-baseline
monthly-client-report
certificate-rotation
client-onboarding
```

An operation pack can provide:

* versioned operation definitions;
* referenced scripts/templates;
* tests and fixtures;
* supported provider/target metadata;
* compatibility declarations;
* migration/import helpers when appropriate.

Private repositories/registries and hosted catalogs are possible ecosystem layers, not Core
runtime requirements.

## 18. Policy, approval, security, and evidence

Do not create another policy engine here. Operations project their required capabilities and
effects into the policy/approval/security contracts owned by `mcp.md` and domain plans.

Security invariants include:

* imported scripts/workflows are untrusted data until their operation is validated;
* import/compatibility analysis never authorizes execution;
* source artifacts cannot introduce new hosts, credentials, capabilities, or effects outside
  the shared capability/network/policy model;
* AI-generated normalization or compatibility suggestions cannot weaken policy or approval;
* raw credentials are references/resolved resources, never serialized operation values;
* an approved plan fingerprint cannot be reused after any nested/domain plan changes.

Operation-level evidence should assemble references needed to answer:

```text
what operation definition ran?
which source revision produced it?
what plan was approved?
who/what authorized apply?
which providers/targets were touched?
what changed?
what verification succeeded or failed?
which artifacts/request IDs support the result?
```

Evidence is redacted by default and must never require serializing resolved secret material.
Artifact storage/lineage stays with `artifact-conversion.md`; run/execution events stay with
the owning execution/orchestration contracts.

## 19. Service and CLI expectations

The reusable operations service should support behavior shaped like:

```text
load / inspect
validate
plan
apply
verify
import
compatibility
status/diff deployment
deploy
```

The actual Click command tree belongs to `cli.md`. A likely user experience is:

```text
riko operation validate NAME
riko operation plan NAME
riko operation apply NAME
riko operation verify NAME
riko operation import PROVIDER ...
riko operation compatibility NAME --target TARGET
riko operation diff NAME --target TARGET
riko operation deploy NAME --target TARGET
```

CLI commands must be thin adapters over Python-callable services so the same operation can be
used from tests, APIs, MCP, hosted control planes, or external orchestrators.

## 20. End-to-end scenario audits

These scenarios are architecture checks. Their purpose is to expose missing ownership or contracts,
not to promise that every named provider already implements the adapters.

### 20.1 SuperOps script → Git → GitHub Actions

```text
SuperOps provider discovers/acquires script + metadata
    ↓ provider-integrations.md
preserve original artifact/provenance
    ↓ operations-as-code.md
normalize to proposed OperationSpec
    ↓
validate required shell/runtime/capabilities
    ↓ mcp.md shared CapabilityCatalog + provider target facts
compatibility(OperationSpec, target=github-actions)
    ↓ operations-as-code.md
OperationPlan for deployment
    ↓ policy/approval if target mutation requires it
provider target exporter/deployer generates/publishes workflow artifact
    ↓ provider-integrations.md
GitHub Actions schedules/runs derived artifact
    ↓ orchestration.md
inspect deployed target identity/fingerprint
    ↓ provider-integrations.md
compare with Git source for automation drift
    ↓ operations-as-code.md
```

The compatibility report must flag SuperOps-only variables, triggers, secrets, or actions that have
no GitHub Actions equivalent. A preserved PowerShell script can remain `portable_with_script` even
when surrounding workflow semantics require adaptation. Editing the generated workflow in the target
creates deployment drift; it does not redefine the canonical operation.

### 20.2 Windows Autopilot onboarding with approval and long waiting

```text
OperationSpec references Autopilot desired-state operation
    ↓
validate tenant/input/capability requirements
    ↓
plan delegates Microsoft state diff to ChangePlan
    ↓ microsoft-administration.md
OperationPlan references ChangePlan fingerprint
    ↓
MCP/domain policy requires human approval
    ↓
apply exact approved OperationPlan
    ↓
Microsoft/Graph provider starts import/sync
    ↓
OperationHandle
    ↓ provider-integrations.md wait_operation
bounded long wait / optional durable orchestrator handoff
    ↓ orchestration.md
Microsoft authoritative verification
    ↓ microsoft-administration.md
operation verify/evidence assembly
```

This scenario requires the `OperationPlan` fingerprint to incorporate the referenced `ChangePlan`
fingerprint. If Microsoft state changes enough to produce a different `ChangePlan`, previous approval
cannot authorize the new plan. `OperationHandle` waiting remains provider-owned even if an
orchestrator persists the handle and resumes it later.

These two audits deliberately cover both migration/deployment portability and direct provider
administration. No additional generic runtime abstraction is required by either flow.

## 21. Testing strategy

Contract tests should cover at minimum:

1. operation serialization contains no resolved secret material;
2. operation identity/fingerprint is stable for the same canonical definition;
3. referenced script/artifact changes affect operation reproducibility identity;
4. overlays resolve deterministically without copying operation logic;
5. validate performs no provider mutation;
6. plan reports opaque/unsupported steps instead of fabricating diffs;
7. plan-bound approval is invalid after plan-changing drift;
8. referenced domain-plan fingerprint changes invalidate OperationPlan approval;
9. apply uses normal Pipeline/capability execution contracts and never silently re-plans;
10. verify reads authoritative provider/domain state when supported;
11. deployment metadata links vendor copies back to source revision/fingerprint;
12. automation drift distinguishes outdated, modified, missing, and unverifiable copies;
13. import preserves source artifacts and provenance;
14. compatibility analysis reports lossy/unsupported mappings explicitly;
15. AI-assisted normalization cannot bypass validation/review/policy;
16. an RMM-to-RMM fixture preserves portable scripts and flags vendor-only semantics;
17. manual handoffs survive import and round-trip serialization;
18. external schedulers/runners remain targets rather than new canonical sources;
19. SuperOps→GitHub Actions fixture separates provider facts from the common CompatibilityReport;
20. Autopilot fixture preserves approval identity across ChangePlan/OperationPlan and
    OperationHandle waiting.

Test-layer placement and deduplication rules are owned by `testing.md`; provider-specific importer/
deployer contract tests stay with `provider-integrations.md`.

## 22. Implementation phases

```text
OA0  architecture + OperationSpec ownership boundary
OA1  repository loader + reproducibility metadata/fingerprints
OA2  validate + cross-domain OperationPlan aggregation
OA3  apply + verify service over existing Pipeline/capability contracts
OA4  environment/client overlays
OA5  deployment target integration + source-revision metadata
OA6  automation-drift comparison
OA7  common import/provenance/lossiness model
OA8  first RMM importer + CompatibilityReport
OA9  first cross-RMM migration fixture
OA10 operation-pack registration/examples
OA11 CLI adapters after reusable services stabilize
```

Provider-specific importer/deployer interfaces must land through the provider owner; capability
resolution/policy through MCP; scheduling/run-boundary integration through orchestration. The
cross-gameplan implementation dependency is sequenced by `implementation-sequence.md` rather than
redefined by OA numbering.

Live implementation status belongs in `PHASE_CHECKLISTS.md`, not in this gameplan.

## 23. Explicit non-goals

This plan does not make Riko Core:

* a durable scheduler or daemon;
* an RMM/PSA replacement;
* a hosted workflow UI;
* a universal infrastructure resource manager;
* a second secrets store;
* a second generic state/checkpoint implementation;
* a second capability/policy catalog;
* a second workflow/DAG language;
* an AI agent that may mutate systems without deterministic policy;
* a guarantee that every vendor automation can be translated losslessly.

A future hosted control plane may manage repositories, approvals, runners, fleet deployment,
drift, evidence, and collaboration. That is an ecosystem/product layer consuming these
contracts, not a requirement of Riko Core. Commercial strategy and vertical packaging are tracked in
`commercialization.md` so they cannot silently turn into Core architecture requirements.

## 24. Definition of done

1. Git/version-controlled files can be the canonical source for an operation without a
   vendor UI becoming authoritative.
2. An operation reuses Riko Pipeline/workflow/capability contracts rather than creating a
   parallel executor or capability catalog.
3. `validate → plan → apply → verify` works across supported domains, with policy/approval between
   plan and apply, while honestly marking opaque or unsupported steps.
4. Operation-level reproducibility records identify the source revision, inputs, relevant
   artifacts, package/provider identities, referenced domain-plan identities, and approved plan
   without containing secrets.
5. The same operation can resolve for multiple client/environment overlays without source
   duplication.
6. Derived vendor deployments can be compared to the Git definition for automation drift.
7. Importers can preserve scripts, workflow definitions, runbooks/work plans, provenance,
   and manual handoffs.
8. Compatibility reports quantify migration loss before a target deployment is attempted and never
   imply universal lossless portability.
9. Provider-specific extraction/deployment remains in provider integrations; capability discovery
   and policy remain in MCP; scheduling remains in orchestration; runtime/state remains in Core
   owners.
10. SuperOps→GitHub Actions and Autopilot approval/long-wait scenarios compose existing owners with
    no new generic runtime contract.
11. Riko Core remains accurately describable as a configurable pipeline engine for Python;
    Operations as Code is a capability of the broader Riko ecosystem built on that engine.
