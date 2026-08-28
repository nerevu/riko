# Windows Autopilot provisioning gameplan

## 1. Mission

Define the **first concrete `riko-microsoft` integration**: a CSV-driven Windows Autopilot
new-device automation that performs the current manual Intune workflow centrally from the MSP
machine, starting from one or more existing hardware-hash CSV files. This is a **scenario** that
specializes the generic Microsoft contracts — it owns only Autopilot-specific input models, tag
rules, state machine, and workflow sequencing.

> **Dependencies:** P14 external distribution (`riko-microsoft`), gated behind P8
> (entry points) + P11 (pub/sub) + P12 (errors/events); see
> [MILESTONES.md](../MILESTONES.md) "External distributions". It is the downstream *consumer* that
> the [module-enums.md](module-enums.md) plan references as the fake-then-real example extension
> proving the P8 seam. **No Microsoft imports or dependencies land in `nerevu/riko`.**
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
* [module-enums.md](module-enums.md) — P8 registration + the `microsoft.autopilot.*` module ids and
  the generated `MicrosoftModule`/`Module.Microsoft.Autopilot.*` discovery enums;
* [connectors.md](connectors.md) — credential references (never serialized secrets).

## 2. Ownership boundary

**This plan owns:** the Autopilot input model + canonical tag derivation, multi-CSV ingestion/dedup
rules, deployment-intent manifest, the Autopilot device state machine + operations, import/sync/
profile/60-minute-fallback specifics, the operator API + `riko-ms` CLI surface, and the scenario
DoD/tests.

**It does not own** (link out): `MicrosoftContext`/auth/Graph client, `ChangePlan`/preflight/verify
semantics, `OperationHandle`/waiting, retry/throttling classification, or the module-enum codegen.

**The four-layer rule** — do not collapse these into one module:

```text
CSV ingestion  = a source
Microsoft Graph = an adapter
Autopilot desired state = the domain service
Riko's registry = the exposure mechanism
```

`client.py` is a thin translation between typed operations and Graph — **no business rules**. The
existing PowerShell scripts (`inspiration/UploadDeviceHash.ps1`) stay reference/fallback only; extract their
semantics into typed components — do **not** reproduce them in Python.

## 3. Scope

**MVP:** one/many Microsoft-format hardware-hash CSVs (no physical merge); normalization + dedup;
validation before writes; central app-only auth; explicit tenant context; existing-device
discovery; import of missing devices; canonical group-tag assignment; Admin-device user assignment;
idempotent reruns; import polling with timeout; Autopilot sync; deployment-profile monitoring;
60-minute profile fallback; post-write verification; dry-run/plan mode; structured results/errors;
tests with a fake Graph transport.

**Out of scope:** hardware-hash acquisition; running Riko on client VMs; PowerShell dependency for
the normal path; browser/Playwright/Intune-portal/CIPP automation; arbitrary group tags; device
reset/wipe; existing-device retirement/deletion; generic Microsoft administration beyond this
workflow.

## 4. Input model & canonical tags

Normalize every CSV row into hardware, then combine with deployment intent (frozen slotted
dataclasses):

```python
class AutopilotHardware:
    serial_number, hardware_hash, product_id = None


class FormFactor(StrEnum):
    DESKTOP = "Desktop"
    LAPTOP = "Laptop"


class DeviceMode(StrEnum):
    ADMIN = "Admin"
    SHARED = "Shared"


class Ownership(StrEnum):
    CLIENT = "Client"
    MSP = "MSP"


class AutopilotDeviceSpec:
    hardware, form_factor, mode, ownership, assigned_user = None
```

`group_tag` is **derived, never primary input** — `f"{form_factor}-{mode}-{ownership}"`, so the
allowed output is **exactly eight** canonical tags (`Desktop-Admin-Client` … `Laptop-Shared-MSP`).
Formalize the three dimensions the scripts already encode instead of retaining string manipulation.

## 5. CSV ingestion & deployment intent

`load_autopilot_csv(path)` / `load_autopilot_csvs(paths)` — concatenate + dedup **in memory**, no
temp combined CSV. Validate: required `Device Serial Number` + `Hardware Hash`; recognized Microsoft
headers; nonempty normalized serial; valid hash; duplicate serials; conflicting hashes per serial.
**Duplicate + identical hash → dedupe; duplicate serial + different hashes → fail preflight. Never
partially import a batch that failed input validation.**

Deployment intent is a separate manifest (`serial_number,form_factor,mode,ownership,assigned_user`)
joined by serial. Rules: **Admin ⇒ `assigned_user` required**; Shared ⇒ normally absent;
form_factor/mode/ownership restricted to their enums. Do **not** infer MSP ownership from hostname/
username unless later made an explicit configurable policy.

## 6. Authentication (consumes azure-automation §4/§7)

Use the existing `MicrosoftContext(tenant_id, credential, cloud, operator_id, correlation_id)`.
Credentials stay **references, not serialized secrets**; tenant/session state stays execution-scoped
to prevent MSP cross-tenant leakage. Credential preference: managed/workload identity → certificate
SP → client secret only when necessary. Never introduce `app_secret="..."` into `AutopilotDeviceSpec`,
pipeline config, or serialized plans. Autopilot ops need Graph app permission
`DeviceManagementServiceConfig.ReadWrite.All`.

## 7. Graph & Autopilot clients (consumes azure-automation §8)

`GraphClient.request(...)` owns transport only: token acquisition, auth header, base-URL/API-version,
JSON, pagination, request IDs, normalized Graph exceptions, `Retry-After`, HTTP error classification.
It does **not** own Autopilot rules, desired-state comparison, retry loops, waiting, or approval.

`AutopilotClient` above it exposes typed operations: `list_registered_devices`/`find_registered_device`,
`list_imported_devices`/`get_imported_device`, `import_devices`, `update_device_properties`/
`assign_user`, `sync`, `get_profile_state`/`assign_profile`. **Use v1.0 where stable** (imported-device
list/import, `updateDeviceProperties`, `assignUserToDevice`); **isolate beta behind explicitly named
adapter methods** (Autopilot `sync` + direct profile assignment are beta) — do not scatter "beta"
strings through the reconciler.

## 8. Preflight, planning, apply-verify (consumes microsoft-administration §6/§8/§11)

**Preflight** before any mutation: credential resolves; token acquirable; tenant matches customer;
Graph reachable; permission available; all CSV/intent rows valid; all Admin users resolvable; every
serial has intent; every desired tag valid + maps to a deployment profile; no conflicting duplicate
serials → else `failed_preflight` **before any write**.

**`plan_autopilot_devices(specs, *, context) -> ChangePlan`** — per serial classify one state:
`MISSING`, `EXISTS_CONVERGED`, `EXISTS_TAG_DRIFT`, `EXISTS_USER_DRIFT`, `EXISTS_PROFILE_DRIFT`,
`IMPORT_PENDING`, `IMPORT_FAILED`; emit operations: `ImportDevice`, `UpdateGroupTag`, `AssignUser`,
`WaitForImport`, `SyncAutopilot`, `WaitForProfile`, `AssignProfileFallback`, `NoChange`. **No writes
during planning.** A rerun against converged devices ⇒ all `NoChange` ⇒ `changed=False`
(desired-state contract).

**`ensure_autopilot_devices(specs, *, context, dry_run=False) -> AdminResult`**:
`preflight → discover → plan → (dry_run ⇒ return plan) → apply → wait → verify → AdminResult`. A Graph
"write succeeded" is **not** sufficient — do an **authoritative read after mutation** and distinguish
provider response from verified state.

## 9. Import, waiting, sync, profile fallback

**Import** — prefer the batch action `POST /v1.0/…/importedWindowsAutopilotDeviceIdentities/import`
with each record carrying serial + hardware id + group tag + assigned user immediately. Do **not**
issue one HTTP request per CSV row.

**Waiting** (consumes provider-integrations §18) — never `while True: sleep(15)` inside the client.
Represent progress as `OperationHandle(provider="microsoft", operation_id=…,
status_capability="microsoft.autopilot.import_status")` and use the shared waiter. Configurable
bounds: import 15 s / 15 min; registration 15 s / 15 min; profile 15 min / 60 min.

**Sync + profile** — after registration trigger Autopilot sync (tolerate already-running/throttled;
it returns initiation, not convergence), then query authoritative state. Maintain
`PROFILE_BY_GROUP_TAG` loaded **by tenant/environment** — never hard-code real profile ids in source.

**60-minute fallback** — poll actual vs. desired profile up to 60 min; if desired appears → verify;
if still genuinely unassigned → `AssignProfileFallback` → verify again. **If a *different* profile is
already assigned, return a conflict requiring explicit policy/approval — never silently overwrite.**

## 10. Operator API, CLI, and P8 registration

Primary API is the high-level `ensure_autopilot_devices(...)`; do **not** expose the low-level
sequence as the primary surface. CLI: `riko-ms autopilot plan|apply|status` (globbed `hashes/*.csv`,
`--manifest`, `--tenant`).

Register through the P8 entry-point seam once independently testable —
`[project.entry-points."riko.modules"] microsoft = "riko_microsoft.modules:definitions"` — exposing
`microsoft.autopilot.ensure` / `microsoft.autopilot.status`. The generated discovery enum
(`MicrosoftModule.AUTOPILOT_ENSURE`, aggregate `Module.Microsoft.Autopilot.ENSURE`) is
[module-enums.md](module-enums.md)'s concern; strings stay canonical
(`SyncPipe("microsoft.autopilot.ensure")`). **No `nerevu/riko` edit required.**

Proposed `riko-microsoft` layout: `auth/context/graph/errors/operations` + `autopilot/{models,csv,
tags,profiles,client,planner,reconciler,status,capabilities}` + `modules/autopilot.py`.

## 11. Implementation order

Stable path first, then layer sync/profile:

1. Autopilot models + canonical tag rules → 2. multi-CSV parser/normalizer → 3. `MicrosoftContext`
+ credential-reference auth → 4. generic Graph client → 5. read/discovery client → 6. `ChangePlan`
generation → 7. v1.0 import/update/user ops → 8. import/registration `OperationHandle` adapters →
9. reconcile/apply + authoritative verify → 10. isolated beta sync adapter → 11. profile-state
monitoring → 12. 60-minute fallback → 13. CLI → 14. P8 registration → 15. full contract/integration
suite. **Do not** start with PowerShell, browser automation, or the profile fallback.

## 12. Definition of done

From the MSP machine, `riko-ms autopilot apply ./hashes/*.csv --manifest ./devices.csv --tenant
client-a` — without opening Intune or touching the new device — validates all input, authenticates
to the correct tenant, imports only missing devices, applies canonical tags, assigns Admin users,
waits with bounded timeouts, syncs, verifies profile assignment, performs the configured 60-minute
fallback, verifies final authoritative state, produces machine-readable per-device results, reruns
safely with `changed=False`, and keeps secrets out of plans/logs.

## 13. Required tests (fake Graph transport)

Cover: **CSV** (one/many parse; identical dup deduped; conflicting serial/hash fails; missing column
fails); **domain** (all eight tags; invalid factor/mode/ownership rejected; Admin-without-user
rejected); **auth/context** (credential reference not secret; tenant A/B cannot leak); **planning**
(missing→Import; converged→NoChange; wrong tag→update; wrong/missing Admin user→assign; dry-run zero
writes); **import** (batch payload; pending stays pending; complete succeeds; provider error →
structured failure; timeout terminates); **idempotency** (second converged run → zero mutations);
**profile** (correct verifies; pending waits; timeout→fallback; wrong existing profile → conflict,
not silent replace); **failure** (permission fails in preflight; 429 honors retry hint; timeout →
`timed_out`; verify failure → `failed_verify`); **security** (no tokens/secrets in logs; `ChangePlan`
carries no secret material); **P8** (loads through entry point; no core edit).
