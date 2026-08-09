# Riko Microsoft Administration and Desired-State Automation Gameplan

## 1. Mission

Turn the useful patterns from the Microsoft 365 and Entra automation inspiration into a
safe, testable administrative automation layer built on the existing
`_docs/gameplans/azure-automation.md` architecture.

This plan does not replace the Azure automation gameplan. It sharpens the administrative
workflow contract around desired state, privilege, dry-run, verification, audit evidence,
certificate/credential lifecycle, and manual handoffs.

## 2. Inspiration integrated by this plan

### Microsoft 365 admin scripts

Useful patterns:

* explicit service connections and required scopes;
* strongly typed command parameters and validation;
* reusable utility/logging layer;
* read/list operations separated from mutations;
* backup-owner logic expressed as a desired state;
* `DryRun` before membership changes;
* audit-log search with explicit time windows and filters;
* verification after commands whose return/error behavior is unreliable;
* stable process exit codes.

### Entra ID SAML automation

Useful patterns:

* idempotent create-or-update behavior;
* dry-run/force/quiet modes suitable for scheduled execution;
* certificate-expiration threshold checks;
* Government cloud/environment context;
* user/group assignment as desired state;
* generated metadata artifacts and logs;
* explicit partial/manual steps after automation;
* verification/testing after a certificate or SSO change;
* operation-specific exit/status codes.

Do not copy the scripts wholesale or place Microsoft-specific dependencies in Riko core.

## 3. Safety invariant

Administrative automation follows:

```text
resolve tenant + credential
→ discover current state
→ calculate desired state
→ produce ChangePlan
→ authorize / approve
→ apply smallest required mutation
→ verify authoritative state
→ emit audit evidence
```

An AI agent may select from approved capabilities or interpret a request, but it may not
bypass this sequence for privileged/destructive operations.

## 4. Microsoft execution context

Every operation carries explicit tenant/environment context:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class MicrosoftContext:
    tenant_id: str
    credential: str
    cloud: Literal["public", "government", "china"] = "public"
    subscription_id: str | None = None
    operator_id: str | None = None
    correlation_id: str | None = None
```

No mutable global tenant/session state. Concurrent MSP workflows must not leak credentials,
scopes, subscriptions, or PowerShell sessions across clients.

## 5. Capability metadata for administration

Administrative capabilities declare more than an input schema:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class AdminCapability:
    id: str
    risk: Literal["read", "write", "privileged", "destructive"]
    required_scopes: tuple[str, ...]
    supports_what_if: bool
    idempotent: bool
    verifies: bool
```

Scope metadata is both documentation and preflight input. The adapter should fail before a
mutation when known required scopes/roles are absent rather than discovering permission
problems halfway through a batch.

## 6. Service/session preflight

A reusable preflight layer should be able to report:

```text
credential available?
token/certificate valid?
required PowerShell module/command available?
required Graph scopes granted?
service reachable?
tenant/cloud matches configuration?
```

PowerShell module installation must not occur silently inside a production pipeline. A
control-plane/bootstrap command may install or validate dependencies explicitly.

## 7. Desired-state operations

Prefer desired-state capabilities over raw administrative verbs.

Examples:

```python
ensure_group_membership(user="user@contoso.org", group="Finance", present=True)
ensure_channel_owner(user="admin@contoso.org", team=team_id, channel=channel_id)
ensure_license(user="user@contoso.org", sku="Microsoft 365 Business Premium", present=True)
ensure_saml_application(spec=...)
```

Each implementation:

1. reads current state;
2. resolves stable resource IDs;
3. computes whether a change is required;
4. emits a plan;
5. applies only missing/different state;
6. verifies final state.

A second execution against the resulting desired state should produce `changed=False`.

## 8. Change plans

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

Plans must be serializable and safe to display without secret material.

For a backup-owner workflow, for example:

```text
channel A: current owner = user1
           desired owners = user1, backup-admin
           operation = add backup-admin

channel B: already has backup-admin
           operation = none
```

This captures the useful intent of `Add-BackupChannelOwner.ps1` without making its script
shape the public API.

## 9. Dry-run / WhatIf

`dry_run` is a cross-adapter safety contract:

```python
result = capability.invoke(..., dry_run=True)
```

Dry-run may read authoritative state and construct plans, but cannot perform external
mutations.

When using PowerShell, map to `SupportsShouldProcess` / `-WhatIf` where reliable. Still
produce a Riko `ChangePlan`; do not depend only on human-formatted PowerShell WhatIf text.

For REST operations, implement dry-run in the adapter/planning layer.

## 10. Approval policy

Risk determines whether approval is required by default:

```text
read          no approval
write         policy-dependent
privileged    approval normally required
destructive   approval required unless explicitly pre-authorized
```

Typical privileged/destructive examples:

* user/license removal;
* role assignment;
* Conditional Access changes;
* mailbox purge;
* tenant-wide policy changes;
* SAML signing certificate rotation;
* deleting cloud resources.

Approval records should include the plan fingerprint so approval cannot be silently reused
for a materially different mutation.

## 11. Apply then verify

Several Microsoft cmdlets/APIs can return success, partial success, delayed consistency, or
misleading errors. Therefore mutation result and verified state are distinct:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class AdminResult:
    changed: bool
    applied: tuple[OperationResult, ...]
    verified: bool
    final_state: JsonValue | None
    warnings: tuple[str, ...] = ()
```

Verification reads the authoritative endpoint after mutation. For eventually consistent
operations it may use bounded polling with backoff.

A provider error followed by verified desired state may be classified as a warning rather
than automatically replaying a non-idempotent action.

## 12. Long-running operations

ARM jobs, Intune actions, exports, provisioning, certificate propagation, and similar
operations may return asynchronous handles.

Reuse the generic operation/poll contract:

```text
start
→ obtain operation ID
→ optionally subscribe for wake-up events
→ periodically re-read authoritative status
→ terminal state or timeout
```

Event notifications mean "recheck now"; they are not assumed to contain authoritative
final state.

Supported wait modes:

```text
interval
event
hybrid  # preferred when both are available
```

## 13. PowerShell structured I/O

PowerShell remains an optional adapter. Never parse formatted console tables.

The runner uses structured JSON envelopes containing:

```text
success
result
warnings
errors
exit_code
```

and captures raw stdout/stderr separately for diagnostics with secret redaction.

Advanced functions are particularly suitable for tool generation because command metadata
already exposes parameter names/types/validation. Generated tool schemas must still pass
Riko policy and risk classification.

## 14. Audit search as a data source

Unified audit-log search should be modeled as an ordinary finite source capability with
explicit filters:

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

Relative windows such as `7d` may be CLI conveniences, but the resolved timestamps should
appear in the execution plan/events for reproducibility.

Large audit ranges use pagination/checkpoint behavior from the REST/connector plans.

## 15. SAML application desired state

Represent a SAML enterprise application as data rather than command-line switches:

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

The reconciler creates or finds the application, compares settings, adjusts only drift,
then emits federation metadata as an artifact.

## 16. Certificate lifecycle monitoring

Certificate renewal is a monitoring + administration composition:

```text
finite discovery of SAML apps
→ select certificates expiring within threshold
→ ChangePlan
→ approval / dry-run
→ rotate
→ export new metadata artifact
→ verify provider state
→ emit manual-handoff requirement if necessary
```

Configuration includes:

```text
renew_before_days
application selector
force
dry_run
cloud
```

Do not build a separate scheduler. Cron/orchestration decides when the finite certificate
check runs.

## 17. Human/manual handoffs

Some automation cannot safely complete both sides of a federated change. Entra SAML
inspiration explicitly requires uploading new metadata to the service provider and testing
login afterward.

Represent this honestly:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Handoff:
    id: str
    description: str
    artifact: ArtifactRef | None
    required_before_completion: bool
```

A run can be `awaiting_handoff` rather than falsely reporting full completion.

Future ticketing/approval integrations may consume these records; core does not invent a
human-workflow UI.

## 18. Rollback and break-glass metadata

For privileged configuration changes, plans may optionally describe rollback information:

```text
prior assignment set
prior claims configuration
prior certificate identifier
prior policy value
```

Rollback is not automatically safe for every operation. Each capability declares whether a
mechanical rollback exists and whether it needs separate authorization.

Never make emergency/break-glass credentials ordinary serialized parameters.

## 19. Logging and evidence

Administrative events should contain:

```text
run/correlation ID
tenant ID (or safe alias)
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

They must exclude tokens, passwords, private keys, certificate private material, and full
sensitive payloads.

A stable event schema is more useful than reproducing script-specific colored logs.

## 20. Exit/result status

CLI/control-plane execution needs stable machine-readable outcomes. Suggested semantic
states:

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

Adapters may map these to stable process exit codes. Do not make provider-specific numeric
codes the internal data model.

## 21. Testing strategy

Contract tests include:

1. tenant contexts remain isolated under concurrency;
2. missing scope/role fails preflight before mutation;
3. desired-state operation makes no second mutation after convergence;
4. dry-run produces a plan and zero side effects;
5. approval fingerprint changes when planned mutation changes;
6. structured PowerShell wrapper handles result/warning/error envelopes;
7. provider error plus verified desired state is not blindly replayed;
8. audit queries resolve relative ranges to explicit timestamps;
9. SAML reconciliation is idempotent;
10. certificate threshold selects only expiring targets;
11. Government/public cloud endpoint selection is explicit;
12. metadata export produces an artifact reference;
13. manual handoff prevents false full-success status;
14. logs contain audit evidence but no secrets.

## 22. Phases

```text
MA0  AdminCapability + MicrosoftContext metadata
MA1  preflight/scope/module validation
MA2  ChangePlan + dry-run
MA3  desired-state reconcilers + verification
MA4  audit source capability
MA5  SAML application reconciler
MA6  certificate lifecycle monitor/action
MA7  approval/handoff/result-state integration
MA8  audit evidence + rollback metadata
```

## 23. Definition of done

1. Microsoft administration remains outside Riko core dependencies.
2. Every mutation runs in explicit tenant/cloud context.
3. Required scopes and risk are inspectable before execution.
4. Desired-state operations are idempotent where the provider permits.
5. Dry-run produces the same plan path without mutation.
6. Privileged/destructive actions can require approval tied to plan fingerprint.
7. Mutation success is verified against authoritative state.
8. Long-running operations use bounded status polling/event wakeups.
9. SAML/certificate workflows can return explicit manual handoffs.
10. Audit evidence is machine-readable and secret-safe.
