# Windows Autopilot provisioning gameplan

## 1. Mission

Define the **first concrete `riko-microsoft` integration**: a CSV-driven Windows Autopilot
new-device automation that performs the current manual Intune workflow centrally from the MSP
machine, starting from one or more existing hardware-hash CSV files. This is a **scenario** that
specializes the generic Microsoft contracts — it owns only Autopilot-specific input models, tag
rules, state machine, and workflow sequencing.

> **Dependencies:** this remains an external `riko-microsoft` proof built on the shipped P8 entry-
> point seam and the reconciled Pipeline/resource/provider contracts. Forward dependency order is
> owned by [implementation-sequence.md](implementation-sequence.md), especially the provider/external
> integration work in R11/R12. Historical P11/P12/P14 phase labels remain status provenance, not the
> target API contract. **No Microsoft imports or dependencies land in `nerevu/riko`.**
>
> **Provenance.** Folded in from the untracked `_docs/current_implementation.md` (Part 1 — the
> Autopilot implementation plan). Part 2 of that doc (the generated module-enum taxonomy) is owned
> by [module-enums.md](module-enums.md).

Related authoritative plans (this scenario **consumes**, it does not redefine them):

* [azure-automation.md](azure-automation.md) — `MicrosoftContext`, Graph adapter, Microsoft
  credential adapters, Intune adapter, long-running-operation normalization, retry/throttling;
* [microsoft-administration.md](microsoft-administration.md) — preflight, desired-state ops,
  `ChangePlan`, dry-run/WhatIf, apply-then-verify, approval, result states, audit evidence;
* [provider-integrations.md](provider-integrations.md) — `OperationHandle` + interval/event/hybrid
  operation waiting;
* [execution-semantics.md](execution-semantics.md) — Pipeline, Context/resources, retry,
  idempotency, state/checkpoint semantics;
* [module-enums.md](module-enums.md) — registration + the `microsoft.autopilot.*` module ids and
  generated discovery names;
* [connectors.md](connectors.md) — credential references (never serialized secrets).

## 2. Ownership boundary

**This plan owns:** the Autopilot input model + canonical tag derivation, multi-CSV ingestion/dedup
rules, deployment-intent manifest, the Autopilot device state machine + operations, import/sync/
profile/60-minute-fallback specifics, the operator API + `riko-ms` CLI surface, and the scenario
DoD/tests.

**It does not own**: `MicrosoftContext`/auth/Graph client, `ChangePlan`/preflight/verify semantics,
`OperationHandle`/waiting, retry/throttling classification, common StateStore/checkpoint semantics,
or module-enum codegen.

**The four-layer rule** — do not collapse these into one module:

```text
CSV ingestion  = a source
Microsoft Graph = an adapter
Autopilot desired state = the domain service
Riko's registry = the exposure mechanism
```

`client.py` is a thin translation between typed operations and Graph — **no business rules**. The
existing PowerShell scripts (`inspiration/UploadDeviceHash.ps1`) stay reference/fallback only;
extract their semantics into typed components rather than reproducing them in Python.

## 3. Scope

**MVP:** one/many Microsoft-format hardware-hash CSVs (no physical merge); normalization + dedup;
validation before writes; central app-only auth; explicit tenant context; existing-device
discovery; import of missing devices; canonical group-tag assignment; Admin-device user assignment;
idempotent reruns; import waiting with timeout; Autopilot sync; deployment-profile monitoring;
60-minute profile fallback; post-write verification; dry-run/plan mode; structured results/errors;
tests with a fake Graph transport.

**Out of scope:** hardware-hash acquisition; running Riko on client VMs; PowerShell dependency for
the normal path; browser/Playwright/Intune-portal/CIPP automation; arbitrary group tags; device
reset/wipe; existing-device retirement/deletion; generic Microsoft administration beyond this
workflow.

## 4. Input model & canonical tags

Normalize every CSV row into hardware, then combine with deployment intent:

```python
class AutopilotHardware:
    serial_number: str
    hardware_hash: str
    product_id: str | None = None


class FormFactor(StrEnum):
    DESKTOP = "Desktop"
    LAPTOP = "Laptop"


class DeviceMode(StrEnum):
    ADMIN = "Admin"
    SHARED = "Shared"


class Ownership(StrEnum):
    CLIENT = "Client"
    MSP = "MSP"
```

`AutopilotDeviceSpec` combines those values plus optional assigned user.

`group_tag` is **derived, never primary input** — `f"{form_factor}-{mode}-{ownership}"`, so the
allowed output is exactly eight canonical tags (`Desktop-Admin-Client` … `Laptop-Shared-MSP`).
Formalize the three dimensions the scripts already encode instead of retaining string manipulation.

## 5. CSV ingestion & deployment intent

`load_autopilot_csv(path)` / `load_autopilot_csvs(paths)` concatenate + dedup **in memory**; no temp
combined CSV. Validate required `Device Serial Number` + `Hardware Hash`, recognized Microsoft
headers, nonempty normalized serial, valid hash, duplicate serials, and conflicting hashes.

**Duplicate + identical hash -> dedupe; duplicate serial + different hashes -> fail preflight.**
Never partially import a batch that failed input validation.

Deployment intent is a separate manifest (`serial_number,form_factor,mode,ownership,assigned_user`)
joined by serial. Rules: **Admin -> `assigned_user` required**; Shared -> normally absent;
form_factor/mode/ownership restricted to their enums. Do not infer MSP ownership from hostname or
username unless later made an explicit configurable policy.

## 6. Authentication

Use the existing `MicrosoftContext(tenant_id, credential, cloud, operator_id, correlation_id)`.
Credentials stay **references, not serialized secrets**; live tenant clients/sessions remain
execution-owned so concurrent MSP client work cannot leak state between tenants.

Credential preference:

```text
managed/workload identity
-> certificate service principal
-> client secret only when necessary
```

Autopilot operations need the appropriate Graph application permission such as
`DeviceManagementServiceConfig.ReadWrite.All`.

## 7. Graph & Autopilot clients

`GraphClient.request(...)` owns transport only: token acquisition, auth header, base URL/API
version, JSON, pagination, request IDs, normalized Graph exceptions, `Retry-After`, and HTTP error
classification. It does **not** own Autopilot rules, desired-state comparison, retry loops, waiting,
or approval.

`AutopilotClient` exposes typed operations such as:

```text
list/find registered device
list/get imported device
import devices
update device properties
assign user
sync
read profile state
assign fallback profile
```

Use stable Graph APIs where available and isolate beta operations behind explicitly named adapter
methods rather than scattering beta URLs through the reconciler.

## 8. Preflight, planning, apply-verify

Preflight before mutation:

```text
credential resolves
token acquirable
tenant matches customer
Graph reachable
required permission available
all CSV/intent rows valid
all Admin users resolvable
every serial has intent
every desired tag valid and mapped to a profile
no conflicting duplicate serials
```

Failure produces `failed_preflight` before any write.

`plan_autopilot_devices(specs, *, context) -> ChangePlan` classifies each serial into a state such
as:

```text
MISSING
EXISTS_CONVERGED
EXISTS_TAG_DRIFT
EXISTS_USER_DRIFT
EXISTS_PROFILE_DRIFT
IMPORT_PENDING
IMPORT_FAILED
```

and emits operations such as:

```text
ImportDevice
UpdateGroupTag
AssignUser
WaitForImport
SyncAutopilot
WaitForProfile
AssignProfileFallback
NoChange
```

No writes occur during planning. A rerun against converged devices yields only `NoChange` and
`changed=False`.

`ensure_autopilot_devices(specs, *, context, dry_run=False) -> AdminResult` follows:

```text
preflight
-> discover
-> plan
-> dry-run return OR approve/apply
-> wait where necessary
-> authoritative verify
-> AdminResult
```

A provider "write succeeded" response is not sufficient; final state is verified through the
authoritative service.

## 9. Import, waiting, sync, profile fallback

Prefer the Graph batch import action with serial, hardware hash, group tag, and assigned user in the
batch payload. Do not issue one HTTP request per CSV row.

**Waiting** uses the `OperationHandle`/`wait_operation(...)` contract from
`provider-integrations.md`, never a client-local `while True: sleep(...)` loop. Example conceptual
bounds:

```text
import/registration: 15 s interval, 15 min timeout
profile convergence: 15 min interval, 60 min timeout
```

These are operation-wait settings, not `Pipeline.poll()` source-observation semantics.

After registration, trigger Autopilot sync, then read authoritative profile state.
`PROFILE_BY_GROUP_TAG` is tenant/environment configuration; real profile IDs are never hard-coded in
core source.

**60-minute fallback:** wait for desired profile convergence. If still genuinely unassigned after
the configured bound, execute `AssignProfileFallback` and verify again. If a *different* profile is
already assigned, return a conflict requiring explicit policy/approval; never silently overwrite.

If resumable workflow state is required across process/run boundaries, it uses the common
`FeedState` / `StateStore` / CAS model rather than an Autopilot-specific checkpoint store.

## 10. Side effects and idempotency

Autopilot mutations are ordinary Riko/provider side effects. Execution derives the common
idempotency identity from the node/fingerprint/item/generation/iteration dimensions; the provider
adapter must genuinely honor that key where Graph/provider semantics allow it.

Desired-state reads and post-write verification remain the primary protection against duplicate or
ambiguous mutations. Do not add an independent Autopilot retry/idempotency framework.

## 11. Operator API, CLI, and registration

Primary API is the high-level `ensure_autopilot_devices(...)`; do not expose the low-level sequence
as the primary surface.

CLI:

```text
riko-ms autopilot plan
riko-ms autopilot apply
riko-ms autopilot status
```

Register through the existing module entry-point seam once independently testable:

```toml
[project.entry-points."riko.modules"]
microsoft = "riko_microsoft.modules:definitions"
```

with canonical module IDs such as:

```text
microsoft.autopilot.ensure
microsoft.autopilot.status
```

Target Pipeline use is:

```python
Pipeline("microsoft.autopilot.ensure", conf=...)
```

Generated discovery names/enums remain owned by `module-enums.md`. No `nerevu/riko` code edit is
required for the integration.

Suggested `riko-microsoft` layout:

```text
auth/context/graph/errors/operations
autopilot/{models,csv,tags,profiles,client,planner,reconciler,status,capabilities}
modules/autopilot.py
```

## 12. Implementation order

Stable path first, then sync/profile specialization:

1. models + canonical tags;
2. multi-CSV parser/normalizer;
3. MicrosoftContext + credential references;
4. generic Graph client;
5. read/discovery client;
6. ChangePlan generation;
7. stable import/update/user operations;
8. import/registration OperationHandle adapters;
9. reconcile/apply + authoritative verify;
10. isolated sync adapter;
11. profile-state monitoring;
12. 60-minute fallback;
13. CLI adapter;
14. module registration;
15. full contract/integration suite.

Forward cross-cutting runtime order remains owned by `implementation-sequence.md`; this list is the
specialization order inside `riko-microsoft`.

## 13. Definition of done

From the MSP machine, an Autopilot apply command validates all input, authenticates to the correct
tenant, imports only missing devices, applies canonical tags, assigns Admin users, waits with
bounded timeouts, syncs, verifies profile assignment, performs the configured fallback when needed,
verifies final authoritative state, produces machine-readable per-device results, reruns safely with
`changed=False`, and keeps secrets out of plans/logs.

## 14. Required tests

Cover:

- **CSV:** one/many parse; identical duplicate dedupe; conflicting serial/hash fail; missing column
  fail;
- **domain:** all eight tags; invalid factor/mode/ownership rejected; Admin-without-user rejected;
- **auth/context:** credential reference not secret; tenant A/B cannot leak;
- **planning:** missing -> Import; converged -> NoChange; wrong tag/user/profile -> planned change;
  dry-run -> zero writes;
- **import:** batch payload; pending/complete/failure/timeout states;
- **idempotency:** second converged run -> zero mutations; retry identity stable where used;
- **profile:** correct verifies; pending waits; timeout -> fallback; wrong existing profile -> conflict;
- **failure:** permission fails in preflight; 429 honors shared retry hint; timeout -> `timed_out`;
  verify failure -> `failed_verify`;
- **state:** any persisted resumable state uses common StateStore/CAS behavior;
- **security:** no tokens/secrets in logs or ChangePlan;
- **registration:** external package loads through entry point with no core edit.
