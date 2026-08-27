# Microsoft administration gameplan

## 1. Mission

Define the administrative workflow semantics for Microsoft 365, Entra, and Azure changes:
desired state, preflight, dry-run, approval, verification, audit evidence, certificate
lifecycle, and manual handoffs.

This plan consumes the Microsoft adapters in `azure-automation.md`; it does not redefine
tenant context, credential resolution, PowerShell execution, Graph/ARM clients, retry, the
generic capability catalog, or long-running-operation waiting.

Related authoritative plans:

* `azure-automation.md` — `MicrosoftContext`, Graph/ARM/PowerShell adapters, Microsoft
  credential implementations, provider status normalization;
* `connectors.md` — credential references and secret resolution;
* `mcp.md` — generic capability metadata, effects, catalog, and execution policy;
* `execution-semantics.md` — retry, timeout, cancellation, and error policy;
* `provider-integrations.md` — `OperationHandle` and shared operation waiting;
* `orchestration.md` — deployment schedules and durable run boundaries;
* `autopilot-provisioning.md` — a concrete downstream *scenario* (Windows Autopilot new-device
  provisioning) that specializes this plan's preflight/ChangePlan/verify contract.

## 2. Inspiration integrated by this plan

### Microsoft 365 administration

Useful patterns:

* explicit required scopes and service preflight;
* typed command inputs;
* reads separated from mutations;
* backup-owner and membership logic expressed as desired state;
* `DryRun`/WhatIf before changes;
* audit queries with explicit windows and filters;
* verification after provider behavior that can be ambiguous;
* stable machine-readable outcomes.

### Entra SAML automation

Useful patterns:

* idempotent create-or-update behavior;
* certificate-expiration thresholds;
* Government cloud awareness through shared Microsoft context;
* assignments as desired state;
* generated metadata artifacts;
* explicit manual handoffs;
* post-change verification.

Do not copy the scripts wholesale or add Microsoft dependencies to core Riko.

## 3. Ownership boundary

This plan owns:

```text
administrative preflight semantics
Microsoft admin-specific scope/risk metadata
desired-state reconciliation
ChangePlan
dry-run / WhatIf semantics
plan-bound approval
apply-then-verify
administrative audit evidence
SAML/certificate lifecycle workflows
manual handoffs / rollback metadata
admin result states
```

It does not own:

```text
MicrosoftContext                     azure-automation.md
PowerShellResult / PowerShellRunner  azure-automation.md
CredentialProvider                   connectors.md
CapabilityInfo / CapabilityCatalog   mcp.md
RetryPolicy                          execution-semantics.md
OperationHandle / wait_operation     provider-integrations.md
```

## 4. Safety invariant

Administrative automation follows:

```text
resolve MicrosoftContext + credential
→ preflight scopes/dependencies
→ discover authoritative current state
→ calculate desired state
→ produce ChangePlan
→ authorize / approve
→ apply smallest required mutation
→ verify authoritative state
→ emit audit evidence / handoff
```

An AI agent may select from approved capabilities or interpret an unstructured request, but
it may not bypass this sequence for privileged/destructive changes.

## 5. Administrative capability metadata

Generic capability identity, schemas, effects, and catalog behavior come from `mcp.md`.
Microsoft administration attaches domain-specific metadata to that capability identity:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class MicrosoftAdminMetadata:
    capability_id: str
    risk: Literal["read", "write", "privileged", "destructive"]
    required_scopes: tuple[str, ...] = ()
    required_roles: tuple[str, ...] = ()
    supports_what_if: bool = False
    verifies: bool = False
```

This is not a second capability catalog. It augments a shared capability with Microsoft
preflight and administrative-safety facts.

## 6. Service and privilege preflight

Before a mutation, the administrative layer should be able to establish:

```text
named credential resolves?
token/certificate currently usable?
MicrosoftContext tenant/cloud matches target?
required Graph scopes or directory/service roles available?
required PowerShell command/module available?
service reachable?
```

Known preflight failures happen before mutation whenever possible.

PowerShell modules must not install themselves silently during a production pipeline. A
setup/control-plane command may install or validate dependencies explicitly.

## 7. Desired-state operations

Prefer reconciliation capabilities over exposing raw administrative verbs directly:

```python
ensure_group_membership(user="user@contoso.org", group="Finance", present=True)
ensure_channel_owner(user="admin@contoso.org", team=team_id, channel=channel_id)
ensure_license(
    user="user@contoso.org", sku="Microsoft 365 Business Premium", present=True
)
ensure_saml_application(spec=...)
```

Each reconciler:

1. reads authoritative current state;
2. resolves stable provider IDs;
3. computes whether a change is required;
4. produces a plan;
5. applies only missing/different state;
6. verifies final state.

A second execution against converged state should produce `changed=False`.

## 8. ChangePlan

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ChangePlan:
    capability: str
    target: str
    current: JsonValue
    desired: JsonValue
    operations: tuple[PlannedOperation, ...]
    risk: str
    destructive: bool
```

Plans are serializable, fingerprinted, inspectable, and safe to display without secret
material.

Example:

```text
channel A
    current owners: user1
    desired owners: user1, backup-admin
    planned operation: add backup-admin

channel B
    already converged
    planned operation: none
```

## 9. Dry-run / WhatIf

`dry_run` follows the same planning path as execution but performs no external mutation:

```python
result = capability.invoke(..., dry_run=True)
```

Dry-run may:

* resolve context/credentials;
* read authoritative current state;
* run preflight;
* build and validate a `ChangePlan`;
* explain which operations would execute.

It may not perform writes or advance external mutation state.

For PowerShell-backed actions, use `SupportsShouldProcess` / `-WhatIf` where reliable, but
still emit the Riko `ChangePlan`; human-formatted PowerShell output is not the planning
contract.

## 10. Approval policy

`mcp.md` owns the generic execution-policy and approval mechanism. This plan supplies
Microsoft administrative defaults and an additional invariant: approval is bound to the
fingerprint of the exact `ChangePlan`.

Recommended defaults:

```text
read          no approval
write         policy-dependent
privileged    approval normally required
destructive   approval required unless explicitly pre-authorized
```

Examples commonly requiring approval:

* user/license removal;
* directory/service role assignment;
* Conditional Access changes;
* mailbox purge;
* tenant-wide policy changes;
* SAML signing-certificate rotation;
* resource deletion.

A changed plan requires a new authorization decision; approval for one fingerprint cannot
silently authorize another.

## 11. Apply then verify

Provider mutation response and verified state are separate concepts:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class AdminResult:
    changed: bool
    applied: tuple[OperationResult, ...]
    verified: bool
    final_state: JsonValue | None
    warnings: tuple[str, ...] = ()
```

Verification reads the authoritative endpoint after mutation.

When the provider is eventually consistent or returns an asynchronous job, the reconciler
uses the shared `OperationHandle`/`wait_operation` contract from `provider-integrations.md`.
It does not define another generic polling loop.

A provider error followed by verified desired state may be reported as a warning rather
than blindly replaying a non-idempotent mutation.

## 12. Long-running administrative operations

ARM jobs, Intune actions, exports, provisioning, and certificate propagation may be
asynchronous.

The Microsoft adapter normalizes provider state into `OperationHandle`; the administrative
layer only decides what completion means for the change plan and whether verification is
required afterward.

```text
apply planned operation
→ OperationHandle when asynchronous
→ wait_operation(...)
→ authoritative verification
→ AdminResult
```

Generic interval/event/hybrid waiting, timeouts, and wake-up semantics are specified only in
`provider-integrations.md`.

## 13. Audit search as a finite source

Unified audit-log search is an ordinary finite source capability with explicit filters:

```python
pipe.microsoft_audit(
    conf={
        "start": "2026-08-01T00:00:00Z",
        "end": "2026-08-08T00:00:00Z",
        "operations": ["MemberAdded", "MemberRemoved"],
        "user": "...",
        "resource": "...",
    }
)
```

Relative CLI windows such as `7d` resolve to concrete timestamps recorded in execution
metadata for reproducibility.

Graph/REST pagination follows `rest-incremental.md`; durable source-position/checkpoint
lifecycle follows `feed-monitoring.md` when repeated audit collection requires it.

## 14. SAML application desired state

Represent a SAML enterprise application as data:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class SamlAppSpec:
    display_name: str
    identifier: str
    service_provider_metadata: ArtifactRef
    idp_initiated_login_url: str | None
    assignment_required: bool
    assignments: tuple[str, ...]
    claims: tuple[ClaimSpec, ...]
```

The reconciler finds or creates the application, compares the current configuration,
adjusts only drift, verifies the result, and emits federation metadata as an artifact.

## 15. Certificate lifecycle monitoring

Certificate renewal composes existing contracts:

```text
orchestrated finite discovery
→ select certificates inside renewal threshold
→ ChangePlan
→ approval / dry-run
→ rotate through Microsoft adapter
→ wait_operation if asynchronous
→ verify
→ publish new metadata artifact
→ manual handoff when external service-provider action is required
```

Configuration may include:

```text
renew_before_days
application selector
force
dry_run
```

Tenant/cloud come from `MicrosoftContext`; scheduling comes from `orchestration.md`; no
separate scheduler or credential model is defined here.

## 16. Human/manual handoffs

Some federated changes cannot safely complete both sides automatically.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Handoff:
    id: str
    description: str
    artifact: ArtifactRef | None
    required_before_completion: bool
```

A run may end as `awaiting_handoff` rather than falsely reporting success. Ticketing,
approval UI, and human-workflow systems may consume handoffs but are not part of Riko core.

## 17. Rollback and break-glass metadata

Privileged plans may record rollback-relevant prior state:

```text
prior assignments
prior claims configuration
prior certificate identifier
prior policy value
```

Rollback is capability-specific and may require separate approval. Emergency/break-glass
credentials are never ordinary serialized parameters.

## 18. Logging and audit evidence

Administrative evidence should include safe identifiers such as:

```text
run/correlation ID
tenant safe ID/alias
operator/initiator when available
capability ID
plan fingerprint
risk class
approval reference
changed flag
verification status
target resource IDs
provider request IDs
artifact references
```

It excludes tokens, passwords, private keys, certificate private material, and unnecessary
full sensitive payloads.

PowerShell stdout/stderr normalization and redaction are owned by `azure-automation.md`.

## 19. Result states

CLI/control-plane execution should expose stable semantic outcomes:

```text
succeeded_no_change
succeeded_changed
awaiting_handoff
partial
failed_preflight
failed_authorization
failed_apply
failed_verify
timed_out
cancelled
```

Adapters may map these to process exit codes, but provider-specific numeric codes are not the
internal model.

## 20. Testing strategy

Administrative contract tests include:

1. missing scope/role fails preflight before mutation;
2. desired-state operation makes no second mutation after convergence;
3. dry-run produces the same plan and zero side effects;
4. approval fingerprint changes when the planned mutation changes;
5. generic capability policy remains authoritative while Microsoft risk defaults apply;
6. async mutations use the shared `OperationHandle`/wait contract;
7. provider error plus verified desired state is not blindly replayed;
8. audit queries resolve relative windows to explicit timestamps;
9. SAML reconciliation is idempotent;
10. certificate threshold selects only expiring targets;
11. metadata export produces an artifact reference;
12. manual handoff prevents false full-success status;
13. logs contain audit evidence without secrets.

Adapter mechanics are tested in `azure-automation.md` rather than duplicated here.

## 21. Phases

```text
MA0  MicrosoftAdminMetadata + preflight
MA1  ChangePlan + dry-run
MA2  desired-state reconcilers + verification
MA3  plan-bound approval integration
MA4  audit source capability
MA5  SAML application reconciler
MA6  certificate lifecycle workflow
MA7  handoff/result-state integration
MA8  audit evidence + rollback metadata
```

## 22. Definition of done

1. Microsoft administration consumes rather than duplicates Microsoft adapter contracts.
2. Required scopes/roles and administrative risk are inspectable before execution.
3. Desired-state operations are idempotent where the provider permits.
4. Dry-run follows the real planning path without mutation.
5. Privileged/destructive actions can require approval tied to a plan fingerprint.
6. Mutation success is verified against authoritative state.
7. Long-running work uses the shared provider operation-wait contract.
8. SAML/certificate workflows can return explicit manual handoffs.
9. Audit evidence is machine-readable and secret-safe.
10. Generic context, credential, retry, capability, and wait semantics are referenced from
    their authoritative gameplans rather than redefined here.
