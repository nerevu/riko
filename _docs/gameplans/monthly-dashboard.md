# MSP monthly dashboard gameplan

## 1. Mission

Define the **monthly MSP reconciliation scenario** that produces a client dashboard from live
provider APIs — SuperOps, Microsoft Graph (Entra/Intune), Action1, Huntress, and Axcient — synced
into Airtable. This is a **scenario** that specializes the generic connector/provider/Microsoft/
execution contracts: it owns only the canonical device-identity reconciler, the license
calculation, the dashboard target/period model, the monthly workflow sequencing, and the QA
invariant set.

The design replaces the current manual **browser/report-export SOP** (export CSVs from six portals,
CSV-import into Airtable tabs, then hand-resolve "missing" views) with an unattended reconciliation
run. **CSV becomes a compatibility format, not the integration mechanism** — of the manual steps in
the SOP, only a small residue should still require a browser once this lands.

> **Dependencies:** this is an external `nerevu/riko-msp` package built on the shipped P8 entry-point
> seam and the reconciled Pipeline/Context/resource/provider contracts. It reuses the Microsoft
> adapters that [autopilot-provisioning.md](autopilot-provisioning.md) also consumes. Forward
> dependency order is owned by [implementation-sequence.md](implementation-sequence.md), especially
> the provider/external integration work in R11/R12. **No vendor-specific modules or dependencies
> land in `nerevu/riko`.**
>
> **Provenance.** Folded in from the untracked `_docs/reporting.md` design memo (the monthly-
> reconciliation revision of the original CSV export/import SOP). That memo remains the informal
> narrative; the target contract lives here.

Related authoritative plans (this scenario **consumes**, it does not redefine them):

* [azure-automation.md](azure-automation.md) — `MicrosoftContext`, Graph adapter, Microsoft
  credential adapters, Intune/Entra adapter selection, long-running-operation normalization,
  retry/throttling classification;
* [microsoft-administration.md](microsoft-administration.md) — `ChangePlan`, desired state,
  dry-run/WhatIf, approval, apply-then-verify, audit evidence for any **destructive** step
  (license removal, shared-mailbox/proxy-address fixes, provider-side deletes);
* [provider-integrations.md](provider-integrations.md) — SaaS provider CRUD/search, idempotent
  writes, identity mapping, `OperationHandle`/operation wait, and explicit browser fallback;
* [connectors.md](connectors.md) — connector/session lifecycle and credential references
  (never serialized secrets); the Airtable sink transport and its write modes;
* [extensibility.md](extensibility.md) / [module-registry.md](module-registry.md) —
  `riko.ext.register` and package discovery through the `riko.modules` entry-point group;
* [execution-semantics.md](execution-semantics.md) — immutable `Pipeline`/`Context`/resources,
  common idempotency identity, retry, and state/checkpoint semantics;
* [rest-incremental.md](rest-incremental.md) — REST pagination/auth/cursor machinery reused by the
  SuperOps/Action1/Huntress/Axcient provider adapters;
* [module-enums.md](module-enums.md) — the `msp.*` / provider module ids and generated discovery
  names.

## 2. Ownership boundary

**This plan owns:**

```text
canonical DeviceIdentity + the identity-precedence reconciler
license reallocatability calculation (distinct-union semantics)
the monthly dashboard workflow sequencing (source -> normalize -> reconcile -> export)
the Airtable dashboard target: reporting period, generated-at, QA record
the QA invariant set (dashboard "obvious errors" turned into checks)
per-provider device-field normalization schemas
the MonthlyDashboard operator API + small HTTP surface
the scenario DoD/tests
```

**It does not own** (consumed from the plans in §1):

```text
riko.ext.register / entry-point discovery         extensibility.md / module-registry.md
Context -> execution resources / credential refs  execution-semantics.md / connectors.md
generic Airtable/provider sink transports         connectors.md / provider-integrations.md
Microsoft Graph / subscribedSkus adapter          azure-automation.md
ChangePlan / approval / apply / verify            microsoft-administration.md
OperationHandle / operation wait / browser fallback  provider-integrations.md
REST pagination / cursors                         rest-incremental.md
```

**The four-layer rule** — do not collapse these into one module:

```text
provider API (SuperOps/Graph/Action1/Huntress/Axcient)  = a source
Airtable sink                                           = an adapter
device reconciliation + license calc                    = the domain service
Riko's registry                                         = the exposure mechanism
```

## 3. Scope

**MVP:** one client, one reporting period; live-API ingestion for every source that exposes one;
per-provider device-field normalization; the canonical reconciler with deterministic identity
precedence; deterministic dedupe with recorded reasons; distinct-union license calculation from
`subscribedSkus` + user/mailbox reads; Airtable sync via typed sink modes (`append`/`merge`/
`replace`/`delete`) with idempotency keys; QA invariants emitted as a machine-readable record;
period/generated-at stored as data; `plan()` then `apply()`; dry-run; structured per-source and
per-record results.

**Out of scope (consumed or deferred):** the Airtable CSV-import extension; the "New Security
Events" Airtable *form* (create records through the API instead); generic Microsoft administration
beyond this workflow (owned by `microsoft-administration.md`); the shared-mailbox/proxy-address
**remediation** workflow itself (this scenario only *detects* candidates and hands a `ChangePlan`
to the remediation path); Playwright automation of anything an API already covers.

## 4. Sources: replace the export/import SOP with APIs

Each manual "export a report / CSV-import a tab" step becomes a provider adapter feeding an Airtable
sink mode. The `mode` column is the Airtable write semantics, not a CSV-import extension.

| SOP step | Provider adapter | Airtable mode | Key |
|---|---|---|---|
| SuperOps Detailed Asset Inventory | SuperOps GraphQL `getAssetList` | `merge` | `superops_asset_id` |
| Interactive SignIns | Graph `GET /auditLogs/signIns` (period `$filter`) | `merge` | sign-in id |
| Action1 Endpoint Vuln Status | Action1 `GET /reportdata/{org}/{report}/data` | `append` | `(report_month, endpoint_id, source_record_id)` |
| Action1 Hardware Summary | Action1 report-data API | `merge` | `endpoint_id` |
| Installed Windows Updates | Action1 report-data API | `append` | `(report_month, endpoint_id, update_id)` |
| Huntress Agents | Huntress REST agents | `merge` | agent id |
| Huntress monthly report | Huntress REST summary/incident reports | `append` (Security Events) | report-derived id |
| Axcient Usage | x360Cloud API where equivalent, else report export | `merge` | `item_id` |
| Intune Devices | Graph `GET /deviceManagement/managedDevices` | `merge` | `deviceName` / device id |

Notes that change the SOP:

* **SuperOps** — prefer GraphQL (`getAssetList`/`getAsset`/`getAssetSummary`) exposing asset id,
  name, serial, manufacturer, model, hostname, platform, last-comms. The "verify report name / click
  Custom tab" step disappears.
* **SignIns** — `createdDateTime >= period start` and `< next period start`, paginated. No Entra CSV.
* **Action1** — the org/report IDs already in the SOP URLs become API path parameters. For the two
  `append` reports, key on `(report_month, endpoint_id, update_id/source_record_id)` so a rerun is
  idempotent and does not double the month.
* **Huntress** — Agents and most of the monthly report come from the REST API; the Airtable form is a
  human interface, not an integration API, so create Security-Event records directly.
* **Axcient** — the one source to **test before eliminating the browser**: take one current Usage
  export, diff its columns against the x360Cloud API (`/client/{id}`, `/backup_status`, `/user`,
  `/shared_resource`). If everything is present, drop the browser path; if a field is missing, keep a
  **small Playwright fallback for only the unsupported export**, not the whole Microsoft-login /
  x360Portal navigation.
* **Intune** — Graph `managedDevices` (id, `deviceName`, enrollment/last-sync/OS/compliance) replaces
  the CIPP CSV download. CIPP stays useful where its GDAP/MSP abstraction saves auth work; the Riko
  provider surface is `microsoft.managed_devices()`, not `download_csv_from_cipp_page()`.

## 5. Sink interface: `write` vs `sink`, not CSV import

The real Airtable operation is record synchronization, not a CSV-import extension. The scenario
targets one unified sink interface — the decision record for the whole thing. Four verbs on the
collection surface, each on its own axis:

| Verb | Shape | Purpose |
|---|---|---|
| `write(dest, format=, mode=append\|replace)` | passthrough → `Stream` | emit a copy, keep chaining |
| `sink(dest, mode=, keys=, idempotency_key=)` | terminal → `SinkResult`/`Plan` | reconcile records, report/plan |
| `split(n)` / `subscribe(name, on_receive=…)` | branches / subscription | broadcast duplication |
| `export(items, fmt)` | terminal → value | serialize a stream to a Python value |

`write` **emits and continues** (fire-and-forget copy, non-keyed `append`/`replace`, returns the
stream); `sink` **reconciles and reports** (keyed/destructive modes, returns a `SinkResult`/`Plan`).
The discriminator is the return shape: keep the stream (`write`) or get the outcome (`sink`). `write`
desugars to `subscribe(on_receive=…)`.

Reconciliation writes therefore use `sink`:

```python
result = flow.sink(
    "airtable",
    base="apphfQxXXlf9Dajvf",
    table="tbl9FOPBKYC4q28zW",
    mode="merge",
    keys=("endpoint_id",),
)  # -> SinkResult(created=…, updated=…)

flow.sink(
    "airtable",
    table="tbl6EmH19hzEIbSjb",
    mode="append",
    idempotency_key=("report_month", "endpoint_id", "update_id"),
)
```

`merge` upserts on `keys`; `append` uses `idempotency_key` so retries do not duplicate; `replace`
and `delete` are the destructive modes reserved for reconciled removals (§7), gated through
`plan()`/`apply()`. Idempotency identity comes from `execution-semantics.md`; this scenario supplies
only the keys.

**Destination resolution mirrors module discovery** — a destination is named three interchangeable
ways, resolved like any pipe module:

```python
flow.sink("airtable", base=…, table=…)       # bare key -> registry sink
flow.sink(Sinks.AIRTABLE, base=…)            # generated enum (built-ins only)
flow.sink(Airtable(base=…, table=…))         # typed object (externals get this in lieu of an enum)
flow.write("out.csv")                         # path string -> File default, format from extension
```

A string with a path/url signal (a suffix, a `/`, or a `scheme://`) is a `File`; a bare registered
name is that sink. `SinkMode` is the single mode axis; the file-open mode (`wb+`) becomes an internal
`FileTarget` detail (escape hatch `File(url, open_mode=…)`).

Ownership: the verb surface is core collection API; the **mode contract** — `SinkMode` (with
`keyed`/`destructive`), the frozen `SinkWrite`, and `sink_write(mode, keys=, idempotency_key=)` —
lives in `riko/sinks.py`; transports and typed targets (`Airtable`, …) stay external and follow
`connectors.md`; `split`/`subscribe` are owned by `fanout-topology.md`.

Rejected alternatives (recorded so they are not relitigated): `output` is **not** a sink — it is the
compiler's DAG terminal marker (passthrough), excluded from this interface; `mirror`/`cc` conflate
with `split`'s broadcast duplication; `tap` conflates with Singer's source-tap, so the subscriber
side-effect parameter is `on_receive=`, not `tap=`.

## 6. Reconciliation is the heart of the system

The five manual "missing views" collapse into **one canonical device-identity reconciler**. The
Airtable "missing" tabs become **QA outputs, not work queues**.

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

Matching precedence — **never make hostname or asset name the primary identity; they change and they
collide**:

```text
1. exact provider/device IDs
2. exact normalized serial
3. Entra/Intune device relationship
4. exact normalized hostname
5. asset name
6. manual review
```

Every run reports counts rather than opening a view:

```text
matched: 84   new matches: 3   unmatched: 2   ambiguous: 1
```

Dedupe is deterministic — SuperOps on serial then asset name, Huntress on serial — returning a
`DuplicateSet(canonical, duplicates, reason)` instead of requiring a human to open a tab.

**"remove from SuperOps" is a deliberate ambiguity to resolve per deployment:** removing the
duplicate *row from the Airtable SuperOps table* is safe to automate; deleting the asset from the
*actual SuperOps service* is a destructive provider action and must route through
`plan -> approval -> apply` (§8). Same rule for Huntress.

## 7. License calculation comes from Microsoft data, not cross-referencing

Purchased/consumed seats come from Graph `GET /subscribedSkus`:

```python
total = enabled_seats
available = enabled_seats - consumed_seats
```

Reallocatable licenses are a **distinct union**, not a sum — one user can satisfy several categories:

```python
reallocatable = shared_mailbox_ids | shared_email_ids | disabled_licensed_user_ids
```

Store the components *and* the distinct total so the dashboard can show both without over-counting:

```text
Shared mailbox licenses: 4
Shared email licenses: 2
Disabled user licenses: 3
Distinct reallocatable licenses: 7
```

**Shared-email / account-enabled-shared-mailbox fixes are remediation, not dashboard generation.**
`proxyAddresses` is not directly writable through the normal Graph user API, so those changes go
behind the PowerShell/Exchange adapter (`Set-Mailbox`) and are expressed as a `ChangePlan` owned by
`microsoft-administration.md`. Generating a dashboard must never silently mutate Microsoft 365:

```text
monthly_dashboard -> find remediation candidates -> emit ChangePlan
monthly_remediation -> approval -> execute -> verify   (separate run)
```

## 8. Plan/apply for mutations

Reads and Airtable synchronization run unattended. Anything destructive — removing licenses,
changing shared mailboxes, deleting a record from a provider service — produces a change plan first,
consuming the `microsoft-administration.md` / `provider-integrations.md` contract:

```python
plan = await run.plan()
plan.summary
plan.warnings
plan.approvals

result = await plan.apply()
```

A provider "write succeeded" response is not sufficient; final state is verified through the
authoritative service. No independent retry/idempotency framework — reuse the execution contract.

## 9. Dashboard "obvious errors" become QA invariants

The SOP's final "look over dashboard for obvious errors" is automation debt. Turn it into explicit
invariants emitted as a record on every run:

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

The monthly Interface rename ("change name with updated month and year") is cosmetic: store
`Reporting Month` and `Report Generated` as data and let the interface display the period. Only if
Airtable's interface designer cannot bind that dynamically does that single title stay a Playwright
operation — never design a browser robot for one title.

## 10. Operator API and package layout

Primary surface is the high-level run object; the per-source pipeline stays ordinary Riko underneath.

```python
run = MonthlyDashboard(
    client="centralillinoisfriends",
    period="2026-07",
    target=AirtableTarget(base="apphfQxXXlf9Dajvf"),
)

plan = await run.plan()
result = await plan.apply()
```

```python
superops = SyncPipe("superops.assets", conf={"client": client}).normalize_device(
    source="superops"
)
intune = SyncPipe("graph.managed_devices", conf={"tenant": tenant}).normalize_device(
    source="intune"
)

assets = superops.reconcile(intune, keys=["device_id", "serial", "hostname"])
assets.export(
    "airtable",
    base=base,
    table="tblWp7NZAMiKXujkg",
    mode="merge",
    keys=["superops_asset_id"],
)
```

Small HTTP surface:

```http
POST /v1/monthly-dashboard/runs
GET  /v1/monthly-dashboard/runs/{run_id}
GET  /v1/monthly-dashboard/runs/{run_id}/plan
POST /v1/monthly-dashboard/runs/{run_id}/apply
GET  /v1/monthly-dashboard/runs/{run_id}/qa
```

Suggested `nerevu/riko-msp` layout:

```text
riko_msp/
    providers/{airtable,superops,microsoft,cipp,action1,huntress,axcient}.py
    reconcile/{devices,licenses,security}.py
    schemas/{device,signin,patch,license}.py
    workflows/monthly_dashboard.py
    modules/msp.py
```

Register through the existing entry-point seam once independently testable, with no `nerevu/riko`
edit:

```toml
[project.entry-points."riko.modules"]
msp = "riko_msp.modules:definitions"
```

Reuse `nerevu/authorizer` where it saves work (secrets/auth), but do **not** force every provider
call through a mandatory proxy; the reconciled architecture moved away from that.

## 11. Phases

```text
MD0  riko.ext.register + entry-point discovery available (extensibility.md prerequisite)
MD1  execution resources + credential references (execution-semantics.md prerequisite)
MD2  generic Airtable sink: append / merge / replace / delete
MD3  Microsoft Graph provider (signIns, managedDevices, subscribedSkus, users)
MD4  SuperOps GraphQL provider + device normalization
MD5  Action1 report-data provider (idempotent append keys)
MD6  Huntress REST provider (agents + reports -> Security Events)
MD7  Axcient x360Cloud API-vs-export comparison; scoped Playwright fallback only if required
MD8  canonical DeviceIdentity reconciler + deterministic dedupe
MD9  distinct-union license calculation
MD10 QA invariants record
MD11 plan/apply for destructive removals + shared-mailbox/proxy remediation handoff
MD12 MonthlyDashboard operator API + HTTP surface + module registration
```

MD0–MD1 are consumed prerequisites owned by their gameplans; the rest is the specialization order
inside `riko-msp`. Forward cross-cutting runtime order remains owned by
`implementation-sequence.md`.

## 12. Definition of done

1. No vendor-specific module or dependency lands in `nerevu/riko`; `riko-msp` loads through the
   entry-point seam.
2. Every source with a live API is ingested through that API; CSV/browser is fallback only, and each
   residual browser step is named explicitly (Axcient export residue, at most one interface title).
3. Airtable sync uses typed `append`/`merge`/`replace`/`delete` with idempotency keys; a rerun of a
   converged month produces zero duplicate records.
4. Device reconciliation is deterministic with the documented identity precedence; "missing" tabs
   are QA outputs, and every run emits `matched/new/unmatched/ambiguous` counts.
5. Reallocatable licenses are a distinct union with components stored alongside the total.
6. No destructive action (license removal, mailbox/proxy fix, provider-side delete) occurs without a
   `ChangePlan` -> approval -> apply -> authoritative verify; dashboard generation never mutates M365.
7. Reporting period and generated-at are data; "obvious errors" are machine-checked QA invariants
   with a stored record.
8. Generic registry, resources, sink, Graph, plan/apply, wait, and REST pagination are referenced
   from their owning gameplans rather than redefined here.

## 13. Required tests

Cover:

- **providers:** each adapter maps its API response into normalized device/records; pagination uses
  the shared REST contract; Axcient API-vs-export column diff is asserted before dropping the browser;
- **sink:** `merge` upserts on keys; `append` with idempotency key does not duplicate on rerun;
  `replace`/`delete` are gated behind plan/apply;
- **reconciler:** identity precedence order; serial/hostname collisions do not become primary
  identity; ambiguous match reported not silently merged; dedupe returns canonical + reason;
- **license:** distinct-union never exceeds the component sum; components and total both stored;
  disabled/shared-mailbox/shared-email categories intersect correctly;
- **QA:** every invariant emits into the record; a >20% delta or a stale source flips status to
  `warning`; reporting-month consistency enforced;
- **plan/apply:** destructive removal/remediation produces a plan with zero writes in dry-run;
  apply verifies authoritative state; dashboard run performs no M365 mutation;
- **idempotency:** a second converged monthly run produces `changed=False` and no duplicate Airtable
  records;
- **security:** credential references, never serialized secrets; tokens/proxy values redacted from
  logs and plans;
- **registration:** `riko-msp` loads through the entry point with no core edit.
