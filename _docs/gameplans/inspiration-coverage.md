# Inspiration coverage gameplan

## 1. Purpose

The `_docs/inspiration/` directory preserves earlier Nerevu projects and external design
experiments. This index records which ideas are being carried forward into Riko gameplans,
where they belong, and which implementation patterns are intentionally **not** being
revived.

The purpose is traceability, not a commitment to reimplement every legacy feature. A source
is relevant when it demonstrates a reusable contract, user workflow, failure mode, or
architectural boundary that improves Riko's current plans.

## 2. Decision rules

When translating inspiration into Riko:

1. preserve user-facing semantics and operational lessons, not framework-era code;
2. prefer small shared contracts over monolithic services;
3. keep credentials as references and secrets outside serialized workflows;
4. preserve Riko's record-stream core and explicit materialization boundaries;
5. keep scheduling/durable worker ownership outside core;
6. make side effects, state, idempotency, and approximation explicit;
7. reuse existing gameplans instead of creating parallel execution models;
8. keep provider/domain dependencies optional.

## 3. Coverage matrix

| Inspiration | Relevant lessons carried forward | Primary gameplan(s) | Decision |
| --- | --- | --- | --- |
| `365-admin.md` | typed/admin commands, scopes, dry-run, audit queries, shared logging, verification after unreliable provider behavior | `azure-automation.md`, `microsoft-administration.md` | Adopt semantics; keep PowerShell optional |
| `HTTPSanction.md` | auth lifecycle, provider resources, token status/refresh/revoke, webhooks, browser fallback | `connectors.md`, `provider-integrations.md`, `mcp.md` | Adopt capability contracts; reject required auth-proxy service |
| `ams.md` | persisted alert rules, min/max thresholds, enable/disable/restore, firing history | `feed-monitoring.md` | Adopt rule/firing-state vocabulary; reject pickle/Growl specifics |
| `amzn-search-api.rst` | search capabilities, cache policy, environments, credentials, discoverable API | `provider-integrations.md`, `rest-incremental.md` | Adopt provider search metadata; reject standalone wrapper requirement |
| `api-utils.md` | stable serialization, HTTP validators/cache headers, discoverable link index, dependency ordering | `provider-integrations.md`, `connectors.md`, `agents.md` | Adopt validators/catalog concepts; Flask helpers remain historical |
| `authorizer.md` | OAuth1/OAuth2/API-key/service-account providers, uniform resource CRUD, auth callbacks/status | `provider-integrations.md`, `connectors.md` | Adopt normalized auth/resource capabilities; reject monolith |
| `autogen.md` | declarative scenarios, agent teams, RAG, OpenAPI tools, model tiers, generated profiles | `agent-scenarios.md`, `agents.md`, `mcp.md` | Adopt declarative/evaluation ideas; reject self-authorized dynamic tools and unsandboxed code |
| `carbone.md` | durable source/parsed-data/render stages, Jinja/Markdown/HTML/PDF, alternate DOCX templates | `artifact-conversion.md`, `orchestration.md` | Adopt artifact/render boundary and rerenderability |
| `chakula.rst` | RSS tailing, poll interval, finite iterations, initial/backfill, newer cutoff, cache, unique, fail policy | `feed-monitoring.md` | Adopt monitoring semantics; reject endless CLI loop as core scheduler |
| `changanya.md` | Simhash near-duplicates, Bloom approximate membership, Nilsimsa, explicit similarity/error characteristics | `enrichment-modules.md`, `feed-monitoring.md` | Adopt optional near/approx dedupe with explicit semantics; geohash only if a use case appears |
| `ckanny.md` | CKAN CRUD, hash-aware smart update, frequent cron-safe execution, env credential config | `provider-integrations.md`, `connectors.md`, `orchestration.md` | Adopt `if_changed` write policy and CKAN adapter |
| `ckanutils.md` | CKAN Python adapter, resource fetch/search/upload, persistent resource hashes | `provider-integrations.md`, `connectors.md` | Adopt connector/idempotent-write lessons |
| `contacts.md` | heterogeneous contact formats, People API OAuth, PII handling | `artifact-conversion.md`, `provider-integrations.md` | Adopt codec/PII boundaries; do not treat personal exports as fixtures |
| `covid19-il-data-api.md` | source/destination backends, queued jobs, result IDs, status/cache endpoints, bounded date windows | `provider-integrations.md`, `orchestration.md` | Adopt operation-handle/status contract; Redis/RQ optional |
| `csv2html.md` | CSV-to-table rendering, styled HTML artifact | `artifact-conversion.md` | Generalize as table renderer; reject application-specific columns |
| `csv2vcard.md` | record mapping to vCard, chunking, stdin/stdout | `artifact-conversion.md`, `enrichment-modules.md` | Adopt codec + declarative mapping; reject arbitrary serialized lambdas |
| `data-hub-etl.md` | config-driven source series, mappings, API extraction, batched Google Sheets writes | `provider-integrations.md`, `rest-incremental.md` | Adopt mapping/batch-sink patterns; provider-specific logic stays optional |
| `ebay-search-api.rst` | search/pagination/sort/shipping actions, cache, sandbox/live modes | `provider-integrations.md`, `rest-incremental.md` | Adopt typed search/action capability ideas |
| `email-sub-api.md` | feed monitor worker, file/Redis cache, new-entry email action, process separation | `feed-monitoring.md`, `orchestration.md`, `provider-integrations.md` | Adopt monitor/action separation and pluggable state |
| `entra-id-sso.md` | idempotent SAML setup, assignments, certificate renewal threshold, dry-run, gov cloud, artifacts, manual handoff | `microsoft-administration.md`, `azure-automation.md` | Adopt desired-state/lifecycle/handoff contracts |
| `euler.md` | artifact versioning, reproducibility, publishing, notification on versions, library/framework/application layering | `artifact-conversion.md`, `orchestration.md` | Adopt fingerprints/lineage/layering; offline sync/collaboration remains outside core |
| `extractor.md` | async multi-provider enrichment, allow/deny providers, HTTP cache, browser fallback, clean/upsert | `provider-integrations.md`, `enrichment-modules.md`, `highergov-feed.md` | Adopt registry/provenance/cache/upsert patterns |
| `flogger.rst` | structured event persistence, automatic request metadata, batch/NDJSON logging, retention pruning | `productionizing.md`, `orchestration.md`, `provider-integrations.md` | Adopt structured events/retention concepts; reject bespoke logging server requirement |
| `gcontact.md` | resource lookup by name/key/URL, OAuth, range/batch updates | `provider-integrations.md`, `artifact-conversion.md` | Adopt identity resolution and batch mutations; historical library specifics not retained |
| `hdx-age-api.md` | async worker jobs, job/result status, timeout/result TTL/error limits | `provider-integrations.md`, `orchestration.md` | Adopt bounded operation-handle contract; RQ implementation optional |
| `hdx-file-proxy.md` | remote CSV/Excel acquisition, normalized JSON records, chunk limits | `connectors.md`, `artifact-conversion.md` | Adopt connector + codec/chunk boundary; reject permanent proxy service requirement |
| `hdx-scrapers.md` | many source-specific collectors sharing common normalization/output contracts | `connectors.md`, `provider-integrations.md`, `extensibility.md` | Adopt plugin pattern; source-specific scrapers stay outside core |
| `langly.md` | JSON scenarios, semantic model tiers, tools, RAG, supervised/peer teams, evaluation, OpenAPI schema conversion | `agent-scenarios.md`, `agents.md`, `ai-inference.md`, `mcp.md` | Adopt reviewed scenario/evaluation contracts |
| `lego.rst` | multi-source keyed enrichment, threshold comparison, cached lookups, matched/unparsed/unfound outputs | `provider-integrations.md`, `fanout-topology.md`, `enrichment-modules.md` | Adopt join/enrichment/cache/side-output patterns; domain app remains example-level |
| `meetup.rst` | new/changed entity comparison, dedupe, dry-run, vCard output | `feed-monitoring.md`, `artifact-conversion.md` | Adopt change/dry-run semantics and contact codec boundary |
| `nerevu-api.md` | modular provider folders inside a monolith, OAuth, mappings/cache, headless fallback, RQ, sync/store/prune/notify | `provider-integrations.md`, `connectors.md`, `orchestration.md` | Extract reusable contracts; explicitly reject rebuilding the monolith |
| `prometheus-legacy.md` | separation of application/API/data layers; historical domain model | `productionizing.md`, `riko-site.md` | No new core feature; reinforces service/UI separation |
| `proposer.md` | structured YAML context + template → HTML/PDF/Markdown/PNG | `artifact-conversion.md` | Adopt generic RenderPlan/multi-format artifact model |
| `pyconvert.md` | codec inference/override, tabular readers/writers, stdin/stdout, Unicode, chunks, header normalization | `artifact-conversion.md`, `connectors.md` | Adopt codec registry/stream boundaries; optional formats stay extras |
| `sense-hat-b-exporter.md` | long-running metrics exporter consumed by Prometheus | `productionizing.md`, `connectors.md`, `orchestration.md` | Prometheus scrape remains finite connector; exporter/service lifecycle stays deployment-level |
| `webhooks.md` | provider signature verification, payload normalization, dispatch, cache/admin endpoints | `provider-integrations.md`, `orchestration.md` | Adopt verified EventEnvelope; reject arbitrary URL-to-function dispatch |

## 4. Consolidated architecture themes

### 4.1 Monitoring and state

Sources: Chakula, AMS, email-sub-api, Meetup, CKAN tools.

Carried forward:

```text
finite poll
bootstrap/backfill
checkpoint
exact/approx dedupe
changed state
bounded anomaly windows
alert firing state
action fan-out
dry-run
```

Authoritative plan: `feed-monitoring.md`.

### 4.2 Provider integration

Sources: HTTPSanction, authorizer, nerevu-api, data-hub-etl, CKAN tools, Amazon/eBay,
extractor, HDX services, webhooks, contacts.

Carried forward:

```text
credential references
provider/resource/action capability catalog
auth lifecycle
search/CRUD/batch/upsert
cache validators
if-changed writes
identity maps
webhook envelopes
async operation handles
browser fallback
```

Authoritative extension: `provider-integrations.md` plus `connectors.md` and
`rest-incremental.md`.

### 4.3 Administrative automation

Sources: 365-admin, Entra ID SSO, Azure automation notes.

Carried forward:

```text
tenant/cloud context
scope/risk preflight
desired state
ChangePlan
dry-run/WhatIf
approval
apply + verify
audit evidence
long-operation polling
certificate lifecycle
manual handoff
```

Authoritative extension: `microsoft-administration.md` plus `azure-automation.md`.

### 4.4 Agent scenarios

Sources: Langly, AutoGen.

Carried forward:

```text
versioned scenarios
semantic model policies
capability tool grants
shared graph topology
retrieval specs/provenance
reviewed profiles
deterministic evaluations
safety/tool-call assertions
```

Authoritative extension: `agent-scenarios.md` plus `agents.md`, `ai-inference.md`, and
`mcp.md`.

### 4.5 Conversion and rendered artifacts

Sources: pyconvert, csv2vcard, csv2html, proposer, Carbone, Contacts, HDX file proxy,
Euler.

Carried forward:

```text
codec registry
streaming vs materializing formats
declarative field mappings
vCard/contact output
ReportContext
RenderPlan
multi-format rendering
artifact fingerprints/lineage
if-changed publishing
```

Authoritative extension: `artifact-conversion.md`.

## 5. Explicitly rejected legacy patterns

The inspiration directory contains useful history, but the following should **not** return
as Riko architecture:

* Flask monoliths as the mandatory integration layer;
* one standalone proxy web service per external provider;
* plaintext `.env` files or committed service-account/private-key material;
* symlink-based secret distribution as a framework contract;
* mandatory Redis/RQ/memcached/Postgres for ordinary library execution;
* Twisted/gevent as a second execution runtime;
* infinite polling loops hidden inside restartable sources;
* pickle as durable interoperable state format;
* arbitrary Python/function names from untrusted serialized configurations or webhook
  URLs;
* unsandboxed agent code execution;
* agent-discovered APIs becoming immediately executable without policy review;
* materializing unbounded streams for workbook/report conversion;
* domain-specific application schemas in generic Riko modules;
* platform-specific notification systems in core;
* treating HTTP cache state as correctness/checkpoint state;
* treating approximate duplicate detection as exact.

## 6. Cross-plan invariants revealed by the corpus

The repeated projects make several invariants worth enforcing across gameplans:

1. **State has a type.** Source cursor, HTTP cache, identity map, observation history,
   approval state, and artifact version are different things.
2. **Finite work is composable.** Persistent systems should generally repeat bounded Riko
   operations rather than make every connector/process permanently resident.
3. **Side effects need identity.** Upserts, notifications, webhooks, admin mutations, and
   artifact publication require explicit idempotency/change semantics.
4. **Credentials are resources, not record fields.** Serialized workflows carry references.
5. **Provider adapters should expose records/capabilities.** They should not hide a second
   ETL engine.
6. **Artifacts are durable boundaries.** Reports, large documents, cross-process handoffs,
   and rerenderable contexts should be referenced rather than pushed through memory as
   opaque blobs.
7. **Inspection precedes execution.** Pipelines, providers, agent scenarios, admin changes,
   and external dependencies should all be describable without performing side effects.
8. **Verification matters.** Remote mutation success should be checked when provider
   behavior can be asynchronous or ambiguous.
9. **Approximation is declared.** Bloom filters, model judges, inferred schemas, and cost
   estimates must identify their uncertainty.
10. **One capability, many surfaces.** Python, CLI, workflow JSON, MCP, and agent tools
    should project shared underlying services rather than duplicate implementation logic.

## 7. Maintenance rule

When new material is added to `_docs/inspiration/`:

1. add it to this matrix;
2. identify the reusable semantic lesson;
3. map it to an existing authoritative gameplan when possible;
4. create a new gameplan only for a genuinely missing architectural contract;
5. document any tempting legacy pattern that is intentionally rejected;
6. keep implementation details out of core when they belong to optional adapters.

This index should therefore remain a compact architecture traceability document rather than
an archive summary.
