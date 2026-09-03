# MSP monthly dashboard gameplan

## 1. Mission

Define the **monthly MSP reconciliation scenario** that produces a client dashboard from live
provider APIs — SuperOps, Microsoft Graph (Entra/Intune), Action1, Huntress, and Axcient — written
to Airtable.

This scenario specializes generic connector/provider/Microsoft/execution contracts. It owns only:

- canonical device identity/reconciliation;
- license calculations;
- dashboard period/QA data;
- monthly workflow sequencing;
- provider-field normalization for this scenario;
- the `MonthlyDashboard` service/operator surface.

It does **not** own generic Target/write semantics.

The design replaces the current manual browser/report-export SOP (export CSVs from six portals,
CSV-import Airtable tabs, then hand-resolve "missing" views) with an unattended reconciliation run.
CSV becomes a compatibility format, not the integration mechanism.

> **Dependencies:** this is an external `nerevu/riko-msp` package built on the shipped P8 entry-point
> seam and the reconciled Pipeline/Context/resource/provider contracts. Forward dependency order is
> owned by [implementation-sequence.md](implementation-sequence.md), especially R11/R12. No
> vendor-specific dependencies land in `nerevu/riko`.

Related authoritative plans this scenario consumes:

- [effects.md](effects.md) — provider-neutral `write`/Action semantics, WriteResult/ActionResult,
  Target/Format/Resource separation, idempotency participation;
- [connectors.md](connectors.md) — concrete Airtable/HTTP connector Target adapters, credentials, and
  session lifecycle;
- [azure-automation.md](azure-automation.md) — Graph/Microsoft adapters;
- [microsoft-administration.md](microsoft-administration.md) — `ChangePlan`, approval,
  apply-then-verify for destructive Microsoft changes;
- [provider-integrations.md](provider-integrations.md) — SaaS CRUD/search, provider identity,
  OperationHandle/wait, browser fallback;
- [execution-semantics.md](execution-semantics.md) — Pipeline/Context/resources, identity,
  retry/state/checkpoint semantics;
- [extensibility.md](extensibility.md) / [module-registry.md](module-registry.md) — Workflow v2 and
  extension registration;
- [rest-incremental.md](rest-incremental.md) — REST pagination/auth/cursor machinery;
- [module-enums.md](module-enums.md) — generated discovery names.

## 2. Ownership boundary

**This plan owns:**

```text
canonical DeviceIdentity + identity-precedence reconciler
license reallocatability calculation (distinct-union semantics)
monthly workflow sequencing (read -> normalize -> reconcile -> write)
reporting period + generated-at + QA record
the QA invariant set
per-provider device normalization schemas
MonthlyDashboard service/operator API + small HTTP surface
scenario tests
```

**It consumes:**

```text
Workflow v2 / Target / Format structure              extensibility.md
write/action dataflow + result semantics              effects.md
Airtable Target transport / credentials / sessions    connectors.md
provider CRUD/identity/wait/browser fallback          provider-integrations.md
Graph/Microsoft adapters                              azure-automation.md
ChangePlan / approval / apply / verify                microsoft-administration.md
REST pagination / cursors                             rest-incremental.md
Context / state / retry / idempotency identity        execution-semantics.md
```

The four-layer rule:

```text
provider APIs (SuperOps/Graph/Action1/Huntress/Axcient) = readable Targets/provider services
Airtable                                                  = writable Target adapter
device reconciliation + license calculation               = domain service
Riko registries                                            = exposure/discovery mechanism
```

## 3. Scope

**MVP:** one client, one reporting period; live-API ingestion wherever available; provider device
normalization; deterministic identity reconciliation/dedupe; distinct-union license calculation from
Microsoft data; Airtable writes using explicit operation modes such as `append`/`merge`/`replace`/
`delete` where supported; QA record; dry-run/plan/apply for destructive provider changes; structured
source/write/domain results.

A rerun must be convergent/idempotent where the destination supports that contract.

**Out of scope:** generic Airtable/Target write design; generic Microsoft administration; browser
automation for APIs that already expose the needed capability; the actual shared-mailbox/proxy
remediation workflow (this scenario only detects and hands off candidates).

## 4. Sources: replace export/import SOP with APIs

Each manual export/import step becomes a provider read followed by an Airtable write mode. The
`Airtable mode` column below is operation configuration consumed from `effects.md`/the Airtable Target
adapter, not a second `sink()` API.

| SOP step | Provider adapter | Airtable mode | Key |
|---|---|---|---|
| SuperOps Detailed Asset Inventory | SuperOps GraphQL `getAssetList` | `merge` | `superops_asset_id` |
| Interactive SignIns | Graph `GET /auditLogs/signIns` | `merge` | sign-in id |
| Action1 Endpoint Vuln Status | Action1 report-data API | `append` | `(report_month, endpoint_id, source_record_id)` |
| Action1 Hardware Summary | Action1 report-data API | `merge` | `endpoint_id` |
| Installed Windows Updates | Action1 report-data API | `append` | `(report_month, endpoint_id, update_id)` |
| Huntress Agents | Huntress REST agents | `merge` | agent id |
| Huntress monthly report | Huntress REST summary/incidents | `append` | report-derived id |
| Axcient Usage | x360Cloud API where equivalent, else scoped export | `merge` | `item_id` |
| Intune Devices | Graph `GET /deviceManagement/managedDevices` | `merge` | provider device id |

Scenario notes:

- **SuperOps:** prefer GraphQL asset APIs; report-download UI disappears.
- **SignIns:** query period boundaries directly; no Entra CSV.
- **Action1:** org/report IDs become API parameters. Append reports use stable record/month identity so
  reruns do not duplicate the month.
- **Huntress:** agents/reports come from REST; Airtable form is a human UI, not integration API.
- **Axcient:** compare one current Usage export against x360Cloud API fields before eliminating the
  browser. Keep a narrow browser fallback only for an actually missing export capability.
- **Intune:** Graph `managedDevices` replaces CIPP CSV export. CIPP may still be useful as an MSP auth/
  GDAP abstraction, but the Riko-facing capability is provider data, not browser CSV navigation.

## 5. Airtable is a writable Target

The scenario's persistence surface is the common write effect:

```text
records
    -> Pipeline.write(Airtable Target, operation mode/keys/...)
    -> same records continue if the graph continues

WriteResult
    -> EventSink
```

There is no target public `sink()` terminal. Keyed/destructive reconciliation does not require a
second verb; it is write-operation behavior validated against the Airtable Target's capabilities.
Graph position determines terminality.

Conceptually, a scenario may build a configured Airtable Target once and write different tables with
operation-specific configuration:

```python
target = Target(Targets.AIRTABLE, base=base, table=table)

flow = flow.write(
    target,
    mode="merge",
    keys=("endpoint_id",),
)
```

For append-style history:

```python
flow = flow.write(
    Target(Targets.AIRTABLE, base=base, table=security_events),
    mode="append",
    # operation/domain identity participates in the common idempotency contract
)
```

These examples are conceptual target API shape; the authoritative generic contract is `effects.md`.
This scenario owns which business keys/modes to use, not the generic method signature.

Mode meaning for this scenario:

```text
append   add a history/event record with stable idempotency identity
merge    upsert/reconcile current-state records by keys
replace  destructive full-scope replacement; plan/approval when risk requires it
delete   destructive removal; plan/approval when provider/domain policy requires it
```

The execution-derived idempotency identity comes from `execution-semantics.md`; the Airtable adapter
maps that identity to provider behavior where supported.

`output` remains workflow output metadata, not a destination/effect node. `split`/`publish` remain
fan-out topology, not destination aliases.

### Current shipped compatibility

The current `features` branch has `write`/`sink` collection verbs and `riko/targets.py`. Those are
as-built migration inputs documented in `IMPLEMENTED.md`/`CLAUDE.md`; they do not override the target
architecture above. Migration should reuse useful writer/Target mechanics while converging on
`Pipeline.write()` + `WriteNode` + `WriteResult`.

## 6. Reconciliation is the heart of the system

The manual "missing" tabs collapse into one canonical device-identity reconciler. Airtable missing
views become QA outputs, not work queues.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class DeviceIdentity:
    client_id: str
    entra_device_id: str | None = None
    intune_device_id: str | None = None
    superops_asset_id: str | None = None
    action1_endpoint_id: str | None = None
    huntress_agent_id: str | None = None
    axcient_item_id: str | None = None
    serial: str | None = None
    hostname: str | None = None
```

Matching precedence:

```text
1. exact provider/device IDs
2. exact normalized serial
3. Entra/Intune device relationship
4. exact normalized hostname
5. asset name
6. manual review
```

Hostname/asset name are fallback identities, never primary durable identity.

Every run reports:

```text
matched: 84   new matches: 3   unmatched: 2   ambiguous: 1
```

Dedupe is deterministic and returns a reasoned result such as
`DuplicateSet(canonical, duplicates, reason)`.

Removing a duplicate **dashboard row** is different from deleting an asset in a provider service.
Provider-side deletion is a destructive Action/write and must follow the applicable plan/approval/
apply contract.

## 7. License calculation comes from Microsoft data

Purchased/consumed seats come from Graph `subscribedSkus`:

```python
total = enabled_seats
available = enabled_seats - consumed_seats
```

Reallocatable licenses are a **distinct union**, not a sum:

```python
reallocatable = shared_mailbox_ids | shared_email_ids | disabled_licensed_user_ids
```

Store component counts and the distinct total so overlapping users are not double-counted.

Shared-email/account-enabled-shared-mailbox fixes are remediation, not dashboard generation.
`proxyAddresses`/Exchange changes go through the Microsoft administration/PowerShell adapter and a
`ChangePlan`. Dashboard generation never silently mutates Microsoft 365.

```text
monthly_dashboard
    -> detect remediation candidates
    -> emit/handoff ChangePlan

monthly_remediation
    -> approval -> apply -> verify
```

## 8. Plan/apply for destructive mutations

Reads and normal convergent Airtable synchronization run unattended according to configured policy.
Destructive provider changes — license removal, mailbox changes, provider-side deletes — produce a
plan before apply.

```python
plan = await run.plan()
plan.summary
plan.warnings
plan.approvals

result = await plan.apply()
```

A provider "accepted" response is not sufficient where authoritative verification is available.
Use provider/Microsoft wait/verify contracts; do not invent a scenario-local retry/idempotency system.

## 9. Dashboard QA invariants

Replace "look over dashboard for obvious errors" with machine-readable checks:

```text
no duplicate device keys
no negative license counts
no source staler than X days
unmatched assets below threshold
no duplicate serials
no >20% asset-count drop vs prior period
no >20% license-count change vs prior period
no source sync failure
every linked device resolves
reporting month is consistent
```

Example:

```json
{
  "status": "warning",
  "checks": {
    "duplicate_devices": 0,
    "unmatched_assets": 2,
    "stale_sources": 0,
    "asset_delta_pct": -2.3,
    "license_delta_pct": 0
  }
}
```

Store `Reporting Month` and `Report Generated` as data. Only retain a browser operation for a UI title
if Airtable truly cannot bind that presentation dynamically.

## 10. Service/API and package layout

Primary surface is a high-level domain service; its provider pipelines remain ordinary Riko under the
hood.

```python
run = MonthlyDashboard(
    client="centralillinoisfriends",
    period="2026-07",
    target=airtable_target,
)

plan = await run.plan()
result = await plan.apply()
```

Pipeline construction should use the target `Pipeline` API once R4+ lands rather than preserving
`SyncPipe` in the target design. Conceptually:

```text
read SuperOps -> normalize_device
read Intune    -> normalize_device
       \          /
        reconcile
            -> write Airtable(mode="merge", keys=...)
```

Small HTTP surface:

```http
POST /v1/monthly-dashboard/runs
GET  /v1/monthly-dashboard/runs/{run_id}
GET  /v1/monthly-dashboard/runs/{run_id}/plan
POST /v1/monthly-dashboard/runs/{run_id}/apply
GET  /v1/monthly-dashboard/runs/{run_id}/qa
```

Suggested external package:

```text
riko_msp/
    providers/{airtable,superops,microsoft,action1,huntress,axcient}.py
    reconcile/{devices,licenses,security}.py
    schemas/{device,signin,patch,license}.py
    workflows/monthly_dashboard.py
    modules/msp.py
```

Register through entry points with no `nerevu/riko` code edit.

## 11. Phases

```text
MD0  extension registration prerequisite
MD1  execution resources + credential references prerequisite
MD2  Airtable Target adapter + write-mode conformance proof
MD3  Microsoft Graph provider (signIns, managedDevices, subscribedSkus, users)
MD4  SuperOps provider + device normalization
MD5  Action1 report-data provider
MD6  Huntress provider
MD7  Axcient API-vs-export comparison + scoped fallback if required
MD8  canonical DeviceIdentity reconciler + deterministic dedupe
MD9  distinct-union license calculation
MD10 QA invariants record
MD11 destructive ChangePlan/action handoff
MD12 MonthlyDashboard service/API + package registration
```

MD0–MD2 consume Core/R11 contracts. Forward cross-cutting order remains authoritative in
`implementation-sequence.md`; this list is scenario specialization order only.

## 12. Definition of done

1. No vendor-specific dependency lands in `nerevu/riko`; `riko-msp` registers externally.
2. Every source with a usable API is ingested through that API; browser/CSV remains explicit fallback
   only.
3. Airtable synchronization uses the common writable Target/effect model with typed operation modes,
   stable business keys, and idempotency participation; no target public `sink()` contract is
   reintroduced.
4. A converged rerun creates no duplicate history/current-state records where the adapter contract can
   enforce convergence.
5. Device reconciliation is deterministic and emits matched/new/unmatched/ambiguous QA counts.
6. Reallocatable licenses use distinct-union semantics with component counts retained.
7. No destructive Microsoft/provider mutation occurs without its required plan/approval/apply/verify
   path; dashboard generation never mutates M365 as a side effect.
8. Reporting period/generated-at are data and QA checks are machine-readable.
9. Generic Workflow/Target/write/resources/provider/wait/REST contracts are linked to their owners
   rather than redefined here.

## 13. Required tests

Cover:

- **providers:** API responses normalize correctly; pagination uses shared REST contract; Axcient
  API-vs-export fields are compared before browser fallback removal;
- **Airtable write:** merge/upsert keys converge; append identity does not duplicate on rerun;
  unsupported/destructive modes are gated by adapter/domain policy;
- **reconciler:** precedence order, serial/hostname collisions, ambiguity reporting, deterministic
  duplicate reason;
- **license:** distinct-union correctness and stored component totals;
- **QA:** every invariant emits; threshold violations become warnings; reporting-month consistency;
- **plan/apply:** destructive changes produce plans; dry-run performs no writes; apply verifies
  authoritative state;
- **idempotency:** a second converged run produces no duplicate Airtable records;
- **security:** serialized definitions contain credential references, not secrets; events/logs redact
  sensitive values;
- **registration:** external package loads through entry point with no Core edit.
