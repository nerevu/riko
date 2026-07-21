# Claude Code Implementation Gameplan: Riko Site Pipeline

## 1. Mission

Implement a framework-neutral site-generation layer powered by Riko pipelines.

The system must allow Riko to:

1. Fetch data from APIs, files, feeds, or other Riko sources.
2. Normalize and transform records through named Riko modules.
3. Apply AI enrichment and configurable human-review policies.
4. Convert records into versioned `SiteArtifact` objects.
5. Assemble those artifacts into a canonical `SiteSpec`.
6. Export the same `SiteSpec` to:

   * the existing Mithril-based `wei-app`;
   * direct static HTML using htpy;
   * Mithril-powered JavaScript islands;
   * Django;
   * Starlette and FastAPI;
   * Lektor;
   * Pelican;
   * Staticjinja.

The architecture must not make Mithril, Jinja, htpy, Lektor, or Pelican the canonical site model. `SiteSpec` is the canonical boundary.

---

# 2. Repositories and package boundaries

Work across three repositories.

## `nerevu/riko`

Branch from `features`.

Riko core owns:

* pipeline execution;
* module discovery;
* export-target discovery;
* sync/async execution;
* context and lifecycle;
* ordinary record transformations.

Only add the minimum generic extension infrastructure required by `riko-site`.

Do not add site-specific domain types to Riko core.

## `nerevu/riko-site`

Create this as a separate distributable package.

Python package:

```text
riko_site
```

It owns:

* `SiteArtifact`;
* `SiteSpec`;
* site assembly;
* site validation;
* route compilation;
* query evaluation;
* publication/review state;
* approval stores;
* site-related named Riko modules;
* site export target;
* renderer registry;
* Mithril compatibility renderer;
* htpy renderer;
* island manifests;
* server-framework adapters;
* Lektor, Pelican, and Staticjinja adapters.

Suggested extras:

```toml
riko-site[htpy]
riko-site[django]
riko-site[asgi]
riko-site[lektor]
riko-site[pelican]
riko-site[staticjinja]
riko-site[all]
```

## `nerevu/wei-app`

Add only the consumer-side changes needed for:

* generated page and collection definitions;
* initial blog snapshots;
* stale-while-revalidate content loading;
* canonical query execution where practical;
* Mithril island loading;
* compatibility testing.

Do not rewrite the entire application during the compatibility phase.

---

# 3. Non-negotiable architecture decisions

Implement these decisions as stated.

## 3.1 Named modules, not arbitrary application callables

Website transformations must use named Riko modules.

Use:

```python
flow.sitestructure()
flow.siteartifact(...)
flow.sitespec(...)
flow.siteroutes(...)
flow.review(...)
```

Do not add:

```python
flow.pipe(callable)
```

Keep `aggregate(func=...)` as an explicit low-level escape hatch, but do not use it in the canonical examples or implementation.

Use existing modules such as:

```text
rename
filter
sort
strconcat
itembuilder
infer
union
```

for ordinary normalization.

## 3.2 Static-site rendering is an export target

Canonical public API:

```python
result = artifacts.export(
    "site",
    renderer="mithril",
    ...
)
```

or:

```python
result = artifacts.export(
    "site",
    renderer="html",
    engine="htpy",
    ...
)
```

The site export target may accept either:

* a stream of `SiteArtifact` records; or
* a single assembled `SiteSpec`.

## 3.3 Riko pipes remain one-shot executions

Do not make a consumed pipeline restartable.

For multiple render targets:

```python
site = next(
    site_artifacts().sitespec(
        conf={"validate": True}
    )
)

site.render("mithril", ...)
site.render("html", engine="htpy", ...)
```

Alternatively, reconstruct the artifact pipeline for each export.

## 3.4 Component types declare runtimes

Component types remain semantic:

```json
{
  "type": "dashboard"
}
```

Component definitions provide sane runtime defaults.

The compiled `SiteSpec` must always contain a fully resolved runtime:

```json
{
  "type": "dashboard",
  "runtime": {
    "kind": "client",
    "engine": "mithril",
    "load": "visible"
  }
}
```

Instance-level runtime settings may override definition defaults.

## 3.5 htpy is the default direct HTML engine

The direct HTML renderer uses:

```python
renderer="html"
engine="htpy"
```

Do not integrate htpy fragments into Lektor or Pelican in the first implementation.

htpy integration is initially limited to:

* direct static HTML;
* Django;
* Starlette;
* FastAPI.

## 3.6 Lektor uses hybrid record ownership

Use record-level ownership:

```text
content/
├── editor-owned pages
└── _riko_generated/
    └── Riko-owned records
```

Use sidecar enrichment for editor-owned records:

```text
databags/riko-enrichment.json
```

One physical field must have one writer.

Riko must never overwrite editor-owned records.

## 3.7 `wei-app` uses hybrid blog materialization

The data API is build-time:

* pages;
* collection structure;
* navigation;
* routes;
* component definitions;
* query definitions.

The content API remains live at runtime for blog posts.

At build time, Riko generates a blog snapshot for:

* SEO;
* first paint;
* offline fallback;
* fast perceived load.

At runtime, Mithril fetches current blog content and replaces or merges the snapshot.

## 3.8 AI publication policy is configurable

Supported policies:

```text
automatic
draft
approval
```

The default approval workflow produces draft artifacts.

Users approve generated content through either:

* an editorial system; or
* a JSON approval store.

Approvals must be tied to content hashes so regenerated output invalidates stale approvals.

## 3.9 Component rendering is pure

`ComponentContext` provides read-only services and resolvers.

Simple component:

```python
def text(...) -> htpy.Renderable:
    ...
```

Advanced component:

```python
def dashboard(...) -> ComponentRenderResult:
    ...
```

`ComponentRenderResult` may emit:

* rendered node;
* assets;
* metadata;
* island requirements.

It must not emit routes.

Routes must be generated before rendering through `SiteArtifact` records.

---

# 4. Target public API

The implementation should support code shaped like this.

```python
from riko import SyncPipe


def site_artifacts() -> SyncPipe:
    structure = (
        SyncPipe(
            "fetchdata",
            conf={"url": "site/structure.json"},
        )
        .sitestructure()
    )

    programs = (
        SyncPipe(
            "fetchdata",
            conf={
                "url": DATA_API,
                "path": "programs",
            },
        )
        .filter(
            conf={
                "rule": {
                    "field": "active",
                    "op": "is",
                    "value": True,
                }
            }
        )
        .rename(
            conf={
                "rule": [
                    {
                        "field": "name",
                        "newval": "title",
                    },
                    {
                        "field": "college_name",
                        "newval": "college",
                    },
                ]
            }
        )
        .siteartifact(
            conf={
                "kind": "collection_item",
                "target": "programs",
                "key_field": "id",
                "materialization": "build",
            }
        )
    )

    blog = (
        SyncPipe(
            "fetchdata",
            conf={
                "url": CONTENT_API,
                "path": "objects",
            },
        )
        .filter(
            conf={
                "rule": {
                    "field": "published",
                    "op": "is",
                    "value": True,
                }
            }
        )
        .infer(
            conf={
                "field": "body",
                "prompt": "Write a two-sentence summary.",
            },
            assign="description",
        )
        .review(
            conf={
                "policy": "approval",
                "default_status": "draft",
                "approval_sources": [
                    {
                        "type": "json",
                        "path": ".riko/approvals.json",
                    }
                ],
            }
        )
        .siteartifact(
            conf={
                "kind": "collection_item",
                "target": "blog",
                "key_field": "id",
                "materialization": "hybrid",
            }
        )
        .siteroutes(
            conf={
                "collection": "blog",
                "pattern": "/news/{id}",
            }
        )
    )

    return structure.union(
        others=[
            programs,
            blog,
        ]
    )
```

Mithril compatibility export:

```python
result = site_artifacts().export(
    "site",
    renderer="mithril",
    profile="wei",
    output="wei-app/app",
    pages="data/pages.json",
    collections="data/collections.json",
    snapshots="data/snapshots/{name}.json",
    manifest="data/site-manifest.json",
    publication_statuses=("approved",),
)
```

Direct htpy export:

```python
result = site_artifacts().export(
    "site",
    renderer="html",
    engine="htpy",
    output="dist",
    components="site.components",
    layout="site.layout:page",
    assets="site/assets",
    publication_statuses=("approved",),
    sitemap=True,
    manifest=True,
)
```

Preview build:

```python
result = site_artifacts().export(
    "site",
    renderer="html",
    engine="htpy",
    output="preview",
    components="site.components",
    layout="site.layout:page",
    publication_statuses=(
        "approved",
        "draft",
        "rejected",
    ),
    draft_labels=True,
)
```

---

# 5. Core domain model

Use Python 3.12+ typing.

Use frozen, slotted, keyword-only dataclasses where appropriate.

Do not use Pydantic.

Use snake_case in Python and camelCase in canonical JSON serialization.

## 5.1 Required types

Implement at minimum:

```text
JsonValue
SiteArtifact
SiteInfo
SiteSpec
PageSpec
ComponentSpec
ComponentDefinition
CollectionSpec
CollectionItem
QuerySpec
QueryFilter
QueryOrder
RouteSpec
RuntimeSpec
StaticRuntime
ServerRuntime
ClientRuntime
FrameworkRuntime
Materialization
PublicationStatus
ReviewPolicy
PublicationState
ApprovalDecision
BuildResult
AssetRef
IslandSpec
MetadataContribution
ComponentRenderResult
ComponentContext
PageContext
```

## 5.2 Materialization

```python
class Materialization(StrEnum):
    BUILD = "build"
    RUNTIME = "runtime"
    HYBRID = "hybrid"
```

Meaning:

* `BUILD`: data is fully resolved during generation.
* `RUNTIME`: only source and query definitions are generated.
* `HYBRID`: initial snapshot is generated, followed by runtime refresh.

## 5.3 Publication state

```python
class PublicationStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
```

A publication record must include:

```text
status
review_id
content_hash
review_required
reason
```

as applicable.

## 5.4 Runtime resolution

Authoring data may omit `runtime`.

The component registry supplies the default.

The compiled `ComponentSpec` must always contain the resolved runtime.

Validation must fail when:

* a component has no runtime and no default;
* a referenced runtime engine is unavailable;
* a component requests a runtime unsupported by the selected renderer.

---

# 6. Proposed `riko-site` layout

Representative layout:

```text
riko_site/
├── __init__.py
├── py.typed
│
├── types/
│   ├── __init__.py
│   ├── artifacts.py
│   ├── site.py
│   ├── components.py
│   ├── collections.py
│   ├── publication.py
│   ├── routes.py
│   └── rendering.py
│
├── schema/
│   ├── site-spec-v1.json
│   ├── serialization.py
│   └── validation.py
│
├── assembly/
│   ├── __init__.py
│   ├── assembler.py
│   ├── components.py
│   ├── collections.py
│   ├── queries.py
│   └── routes.py
│
├── approvals/
│   ├── __init__.py
│   ├── base.py
│   ├── json_store.py
│   └── composite.py
│
├── modules/
│   ├── sitestructure.py
│   ├── siteartifact.py
│   ├── sitespec.py
│   ├── siteroutes.py
│   ├── review.py
│   ├── sitepublish.py
│   └── siteartifacts.py
│
├── exports/
│   └── site.py
│
├── renderers/
│   ├── base.py
│   ├── registry.py
│   ├── mithril.py
│   ├── html.py
│   ├── lektor.py
│   ├── pelican.py
│   └── staticjinja.py
│
├── html/
│   ├── context.py
│   ├── components.py
│   ├── registry.py
│   ├── htpy_engine.py
│   ├── assets.py
│   ├── metadata.py
│   └── writer.py
│
├── islands/
│   ├── manifest.py
│   └── serialization.py
│
└── adapters/
    ├── django.py
    ├── starlette.py
    ├── fastapi.py
    ├── lektor.py
    └── pelican.py
```

Adapt paths to existing repository conventions, but preserve these responsibility boundaries.

---

# 7. Implementation phases

Complete one phase per pull request unless a phase is explicitly split.

Do not begin framework adapters before the canonical model and compatibility exporter are stable.

## Phase 0: Baseline and architecture records

### Goal

Capture current behavior and lock the agreed decisions before implementation.

### Tasks

1. Run the full existing Riko test suite.
2. Run Pyright using the repository’s current configuration.
3. Record existing export behavior for:

   * list;
   * tuple;
   * CSV;
   * JSON;
   * GeoJSON;
   * OFX/QIF when dependencies are present.
4. Add architecture documents:

   * `SiteSpec as canonical boundary`;
   * `renderer and runtime model`;
   * `publication approval and content ownership`;
   * `one-shot pipeline lifecycle`.
5. Record current `wei-app` `pages.json` and collection-loading behavior as compatibility fixtures.

### Acceptance criteria

* Existing tests pass before feature work.
* Compatibility fixtures are committed.
* No runtime behavior changes in this phase.

---

## Phase 1: Generic Riko export-target registry

### Goal

Replace the hardcoded conversion-function assumption with a generic export-target abstraction without breaking existing exports.

### Core API

```python
class ExportTarget(Protocol):
    name: str

    def export(
        self,
        items: Iterable[Item],
        **kwargs: object,
    ) -> object:
        ...
```

```python
class ExportRegistry:
    def register(
        self,
        target: ExportTarget,
        *,
        replace: bool = False,
    ) -> None:
        ...

    def resolve(self, name: str) -> ExportTarget:
        ...

    def names(self) -> tuple[str, ...]:
        ...
```

### Tasks

1. Introduce `ExportRegistry`.
2. Wrap existing conversion functions in a `FunctionExportTarget`.
3. Preserve all current public `export()` signatures and behavior.
4. Add entry-point discovery:

```toml
[project.entry-points."riko.export_targets"]
site = "riko_site.exports.site:target"
```

5. Load entry points lazily.
6. Make duplicate registrations fail unless `replace=True`.
7. Preserve useful invalid-target errors.
8. Add typed overload support for third-party targets where practical without overcomplicating core typing.

### Tests

* Every legacy export returns exactly the previous type.
* File-writing behavior remains unchanged.
* Registered plugin targets appear in `list_targets()`.
* Duplicate registration fails.
* `replace=True` works.
* Broken entry points report the responsible target.
* Plugin discovery happens once and is deterministic.

### Non-goals

* No site types.
* No renderer registry.
* No `riko-site` code in Riko core.

---

## Phase 2: Canonical `SiteArtifact` and `SiteSpec`

### Goal

Implement the versioned framework-neutral site model.

### Tasks

1. Create the `riko-site` package.
2. Implement immutable domain types.
3. Implement canonical JSON serialization.
4. Add JSON Schema:

```text
site-spec-v1.json
```

5. Implement schema validation.
6. Implement site assembly:

   * site metadata;
   * pages;
   * components;
   * collections;
   * collection items;
   * routes;
   * assets;
   * metadata contributions.
7. Implement component runtime-default resolution.
8. Implement collection materialization metadata.
9. Implement route generation and collision detection.
10. Implement `QuerySpec` validation.
11. Implement a basic query evaluator supporting:

    * equality;
    * inequality;
    * membership;
    * field existence;
    * ascending/descending ordering;
    * limit.
12. Implement `BuildResult`.
13. Implement `SiteSpec.render()` as a convenience wrapper over the site renderer registry.

### Required invariants

* Artifact order does not affect final output except explicit component ordering.
* Duplicate site, page, component, route, or collection keys fail with contextual errors.
* Routes are fully known before rendering.
* Compiled components always contain a runtime.
* Canonical serialization is deterministic.
* Re-serializing equivalent specifications produces byte-stable JSON when pretty-printing settings match.

### Tests

* Complete artifact-to-spec assembly.
* Duplicate-key behavior.
* Missing-reference behavior.
* Runtime-default resolution.
* Runtime override behavior.
* Route collisions.
* Query evaluation.
* JSON Schema validation.
* JSON round trip.
* Deterministic output.

---

## Phase 3: Named site modules and publication review

### Goal

Expose site construction through normal Riko modules.

### Modules

Implement:

```text
sitestructure
siteartifact
sitespec
siteroutes
review
sitepublish
siteartifacts
```

### `sitestructure`

An operator that expands one or more declarative structure documents into artifact records.

It replaces application functions such as `structure_to_artifacts`.

### `siteartifact`

A processor that wraps normalized records as artifacts.

Example:

```python
flow.siteartifact(
    conf={
        "kind": "collection_item",
        "target": "programs",
        "key_field": "id",
        "materialization": "build",
    }
)
```

### `sitespec`

An aggregator/operator that consumes artifact records and emits one `SiteSpec`.

### `siteroutes`

Produces route artifacts before rendering.

Example:

```python
flow.siteroutes(
    conf={
        "collection": "blog",
        "pattern": "/news/{id}",
    }
)
```

### `review`

Applies publication state after AI or other generated transformations.

Example:

```python
flow.review(
    conf={
        "policy": "approval",
        "default_status": "draft",
        "approval_sources": [
            {
                "type": "json",
                "path": ".riko/approvals.json",
            }
        ],
    }
)
```

### Requirements

* Use concrete frozen/slotted config dataclasses.
* Do not use `Objconf` in new site modules.
* Infer module config type from parser annotations.
* Do not manually specify stream return kinds where generator/annotation inference is sufficient.
* Provide sync behavior first.
* Structure interfaces so async parity can be added without changing configuration contracts.

### Tests

* Each module independently.
* Complete chained public API.
* Parser annotation discovery.
* Generator return inference for `sitestructure` and `siteroutes`.
* Invalid config errors.
* No arbitrary callable required in end-to-end examples.

---

## Phase 4: JSON approval store

### Goal

Support Git-managed review decisions without requiring an editorial system.

### Store format

```json
{
  "version": 1,
  "approvals": {
    "article-101:description": {
      "status": "approved",
      "contentHash": "sha256:6dba...",
      "reviewer": "reuben",
      "reviewedAt": "2026-07-19T18:30:00Z",
      "notes": "Checked against the original article."
    }
  }
}
```

### Rules

1. Every generated field requiring approval gets:

   * stable `review_id`;
   * `content_hash`;
   * `draft` status.
2. A decision applies only when its hash matches.
3. A changed generated value becomes draft again.
4. Missing approvals remain draft.
5. Rejected decisions remain rejected until content changes or the decision is changed.
6. Approval-source precedence follows configuration order.
7. The first valid decision for the current hash wins.
8. Malformed stores fail with clear file and field information.
9. Production exporters exclude drafts and rejected records by default.
10. Preview exporters may include them with visible labels.

### Store protocol

```python
class ApprovalStore(Protocol):
    def get(
        self,
        review_id: str,
    ) -> ApprovalDecision | None:
        ...
```

### Tests

* Valid approval.
* Missing approval.
* Stale hash.
* Rejected content.
* Multiple approval sources.
* Source precedence.
* Malformed JSON.
* Draft labeling.
* Production exclusion.

---

## Phase 5: `wei-app` compatibility exporter

### Goal

Generate data consumable by the existing application without making the legacy schema canonical.

### Pipeline

```text
SiteArtifact
→ canonical SiteSpec
→ wei compatibility renderer
→ pages.json and collection artifacts
```

### Generated outputs

At minimum:

```text
wei-app/app/
├── data/
│   ├── pages.json
│   ├── collections.json
│   ├── site-manifest.json
│   └── snapshots/
│       └── blog.json
```

Adapt paths to the current build system where necessary.

### Compatibility mapping

Map canonical values into legacy fields:

```text
ComponentSpec.type       → id
ComponentSpec.props      → flattened component fields
QuerySpec.source         → collection
QuerySpec.order_by       → sorter and sorterDir
QuerySpec.limit          → limit
```

Where the existing app requires named JavaScript filter functions, initially emit both:

```json
{
  "filterer": "postIsPublished",
  "query": {
    "where": {
      "published": true
    }
  }
}
```

The compatibility field preserves current behavior while the canonical query evaluator is introduced incrementally.

### Blog materialization

Generate:

```json
{
  "name": "blog",
  "materialization": "hybrid",
  "snapshot": {
    "source": "/data/snapshots/blog.json",
    "generatedAt": "..."
  },
  "runtime": {
    "url": "/api/blog",
    "strategy": "stale-while-revalidate"
  },
  "query": {
    "where": {
      "published": true
    },
    "orderBy": [
      {
        "field": "publishedAt",
        "direction": "desc"
      }
    ]
  }
}
```

### `wei-app` changes

1. Load the generated snapshot immediately.
2. Populate the collection and render.
3. Fetch the live content API in the background.
4. Normalize the response.
5. Apply the generated query.
6. Merge or replace the snapshot.
7. Redraw only when the visible result changes.

### Snapshot merge rules

Use stable IDs.

For runtime items that match snapshot items:

* runtime source data wins;
* build-only enriched fields may be preserved when the source hash still matches;
* stale enriched values must not be attached to changed source data.

For newly published runtime items:

* use fields supplied by the content API;
* do not run AI in the browser;
* fall back to native excerpt/description fields until the next site build.

### Tests

* Golden-file test against the current `pages.json` shape.
* Page/component ordering.
* Legacy filter/sort compatibility.
* Snapshot first paint.
* Runtime refresh.
* New runtime item.
* Deleted runtime item.
* Preserved enrichment with matching hash.
* Dropped enrichment with changed hash.
* Draft content excluded from production snapshot.
* No SPA-wide rewrite.

---

## Phase 6: Direct htpy renderer

### Goal

Render complete static sites directly from `SiteSpec` using typed Python components.

### Public API

```python
site_artifacts().export(
    "site",
    renderer="html",
    engine="htpy",
    output="dist",
    components="site.components",
    layout="site.layout:page",
)
```

### Component registry

```python
@component(
    "dashboard",
    default_runtime=ClientRuntime(
        engine="mithril",
        load="visible",
    ),
    assets=(
        AssetRef("css/dashboard.css"),
    ),
)
def dashboard(...):
    ...
```

### Read-only context

```python
@dataclass(frozen=True, slots=True)
class ComponentContext:
    site: SiteInfo
    page: PageSpec
    routes: RouteResolver
    assets: AssetResolver
    sanitizer: Sanitizer
    environment: BuildEnvironment
```

Do not expose mutable registration APIs through the context.

### Component return contract

```python
type ComponentOutput = Renderable | ComponentRenderResult
```

```python
@dataclass(frozen=True, slots=True)
class ComponentRenderResult:
    node: Renderable
    assets: tuple[AssetRef, ...] = ()
    metadata: tuple[MetadataContribution, ...] = ()
    islands: tuple[IslandSpec, ...] = ()
```

Normalize simple outputs internally.

### Raw HTML policy

Ordinary strings are escaped.

Raw HTML must be represented explicitly and passed through the configured `Sanitizer`.

Do not silently trust API-generated or AI-generated HTML.

Use a sanitizer protocol rather than hard-coding a specific third-party implementation into the domain layer.

### Renderer responsibilities

* resolve routes;
* render components;
* collect immutable render results;
* deduplicate assets;
* collect metadata;
* write pages;
* copy assets;
* write asset manifest;
* write sitemap;
* write build manifest;
* clean stale generated files only;
* preserve non-generated files.

### Tests

* Static page rendering.
* Nested components.
* Escaping.
* Explicit raw HTML.
* Sanitizer invocation.
* Missing component implementation.
* Unsupported runtime.
* Asset deduplication.
* Metadata aggregation.
* Stable route output.
* Stale-file cleanup.
* Streaming writer support.
* Draft labels in preview output.

---

## Phase 7: Mithril island activation

### Goal

Allow htpy-rendered static pages to activate selected Mithril components.

### Island output

Static HTML marker:

```html
<div
  data-riko-island="dashboard"
  data-riko-props="dashboard-props">
</div>

<script
  id="dashboard-props"
  type="application/json">
  {...}
</script>
```

Manifest:

```json
{
  "dashboard": {
    "module": "/assets/js/islands/dashboard.js",
    "load": "visible"
  }
}
```

### Supported loading strategies

```text
eager
visible
idle
interaction
media
```

### Loader responsibilities

* discover island roots;
* load the manifest;
* dynamically import the named module;
* parse props safely;
* mount Mithril into the root;
* report unknown islands;
* avoid loading static components;
* prevent duplicate mounting.

This is activation, not true DOM hydration.

Mithril may replace or redraw the island root.

Do not describe this as hydration unless a real reconciliation layer is later implemented.

### Cross-island communication

Use DOM custom events for loose coupling.

For highly coupled components, prefer one larger island rather than a global SPA store.

### Tests

* Each loading strategy.
* Unknown module.
* Invalid props.
* Duplicate root.
* Multiple islands on one page.
* No island script on static-only pages.
* Runtime blog refresh inside an island.
* Snapshot rendered before runtime fetch.

---

## Phase 8: Django adapter

### Goal

Reuse htpy layouts and components in Django responses.

### Requirements

* Render a complete `SiteSpec` page to `HttpResponse`.
* Support static asset and route resolvers provided by Django.
* Support ordinary and streaming responses.
* Do not duplicate component implementations.
* Keep Django request objects out of canonical `SiteSpec`.

Example:

```python
def page_view(request, path):
    page = site.resolve_path(path)

    return render_django_page(
        request=request,
        site=site,
        page=page,
        components="site.components",
        layout="site.layout:page",
    )
```

### Tests

* Normal response.
* Streaming response.
* Route resolution.
* Asset URL integration.
* Missing page.
* Client-runtime island output.

---

## Phase 9: Starlette and FastAPI adapters

### Goal

Reuse the same htpy component system for ASGI applications.

### Requirements

* `HTMLResponse` support.
* `StreamingResponse` support.
* Request-aware URL and asset resolution.
* Shared implementation for Starlette and FastAPI where practical.
* No FastAPI-specific types in the canonical domain layer.

### Tests

* Starlette route.
* FastAPI route.
* Streaming body.
* Island output.
* Error handling.
* Async request compatibility.

---

## Phase 10: Lektor exporter

### Goal

Implement record-level hybrid ownership and sidecar enrichment.

### Ownership configuration

```python
site_artifacts().export(
    "site",
    renderer="lektor",
    project="lektor-site",
    ownership={
        "pages": "editor",
        "news": "riko",
        "programs": "riko",
    },
    generated_root="content/_riko_generated",
    enrichment="databags/riko-enrichment.json",
)
```

### Rules

* Write generated records only beneath the configured generated root.
* Never modify editor-owned records.
* Write AI and computed enrichment for editor records into the sidecar.
* Use stable IDs as sidecar keys.
* Include current paths as metadata, not identity.
* Maintain a generated-file manifest.
* Remove stale generated records only when the manifest proves ownership.
* Lektor editorial approval may act as an `ApprovalStore`.

### First-release rendering rule

Use Lektor’s native templates and Flow behavior.

Do not render Lektor components through htpy in this phase.

### Tests

* Generated record creation.
* Editor-owned record preservation.
* Generated deletion.
* Sidecar enrichment.
* Stable ID across path changes.
* Editorial approval source.
* Conflicting JSON/editorial approval precedence.
* Manifest-controlled cleanup.

---

## Phase 11: Pelican exporter

### Goal

Map publication-oriented SiteSpec content to Pelican pages and articles.

### Mapping

```text
SiteSpec page                   → Pelican Page
article-role collection item    → Pelican Article
other collection                → generated data/context
assets                          → Pelican static assets
```

### Requirements

* Article metadata.
* Dates.
* Authors.
* Categories.
* Tags.
* Slugs.
* Summary.
* URL/save paths.
* Feeds.
* Archives.
* Generated-content manifest.
* Draft exclusion.

Use Pelican’s native template system.

Do not embed htpy component rendering in the first release.

### Tests

* Page generation.
* Article generation.
* Draft exclusion.
* Feed output.
* Categories and tags.
* URL/save path behavior.
* Generated-file cleanup.

---

## Phase 12: Staticjinja adapter

### Goal

Provide an optional Jinja-based static renderer consuming the same `SiteSpec`.

### Requirements

* Use the same route compiler.
* Use the same asset resolver.
* Use the same publication filtering.
* Use the same build manifest.
* Use Jinja component templates.
* Keep it optional.
* Do not make Staticjinja a dependency of direct htpy rendering.

### Tests

* Page rendering.
* Component dispatch.
* Routes.
* Assets.
* Draft labels.
* Manifest parity with the htpy renderer.

---

# 8. Renderer and extension registries

Use entry points.

```toml
[project.entry-points."riko.modules"]
sitestructure = "riko_site.modules.sitestructure"
siteartifact = "riko_site.modules.siteartifact"
sitespec = "riko_site.modules.sitespec"
siteroutes = "riko_site.modules.siteroutes"
review = "riko_site.modules.review"

[project.entry-points."riko.export_targets"]
site = "riko_site.exports.site:target"

[project.entry-points."riko.site_renderers"]
mithril = "riko_site.renderers.mithril:renderer"
html = "riko_site.renderers.html:renderer"
lektor = "riko_site.renderers.lektor:renderer"
pelican = "riko_site.renderers.pelican:renderer"
staticjinja = "riko_site.renderers.staticjinja:renderer"

[project.entry-points."riko.site_html_engines"]
htpy = "riko_site.html.htpy_engine:engine"
```

Resolution must be deterministic.

Duplicate names require explicit replacement.

Errors must name:

* the requested extension;
* the responsible entry point;
* the import failure;
* the supported alternatives.

---

# 9. Error hierarchy

Add a site-specific hierarchy in `riko-site`.

```python
class SiteError(Exception):
    pass


class SiteValidationError(SiteError):
    pass


class ArtifactConflictError(SiteValidationError):
    pass


class RouteConflictError(SiteValidationError):
    pass


class UnknownComponentError(SiteValidationError):
    pass


class UnsupportedRuntimeError(SiteValidationError):
    pass


class ApprovalError(SiteError):
    pass


class ApprovalStoreError(ApprovalError):
    pass


class RendererError(SiteError):
    pass


class AssetError(RendererError):
    pass
```

Errors must include relevant keys, paths, component types, route values, or filenames.

Avoid generic `ValueError` for domain failures.

---

# 10. Testing strategy

## Unit tests

Cover:

* every dataclass and serializer;
* runtime resolution;
* query evaluation;
* route generation;
* approval decisions;
* each Riko module;
* each registry;
* each renderer component;
* asset and manifest behavior.

## Contract tests

Create public-contract tests that import only supported APIs.

Do not use internal helpers in contract tests.

Examples:

```python
from riko import SyncPipe
from riko_site import SiteSpec
```

## Golden tests

Use golden fixtures for:

* canonical SiteSpec JSON;
* WEI `pages.json`;
* blog snapshot descriptor;
* htpy HTML;
* island manifest;
* Lektor records;
* Pelican content files.

Normalize nondeterministic values such as timestamps before comparison.

## Integration tests

At minimum:

1. Fake data API.
2. Fake content API.
3. Riko transformation pipeline.
4. AI stage replaced with deterministic test module.
5. Review stage.
6. Site assembly.
7. Mithril export.
8. htpy export.
9. Runtime blog refresh fixture.

## Type checking

New public code must pass strict Pyright checks.

Avoid broad `Any`.

`Any` is acceptable only at deliberate compatibility boundaries and must be localized.

## Performance tests

Add focused tests for:

* large collection assembly;
* query evaluation;
* multi-page rendering;
* asset deduplication;
* streaming page output;
* snapshot/runtime merge.

Do not require full benchmark infrastructure in the first pull request.

---

# 11. Backward compatibility

## Riko

* Existing export targets must behave identically.
* Existing dynamic module chaining must continue working.
* Do not change current pipeline lifecycle in these PRs.
* Do not remove `aggregate`.
* Do not add `.pipe(callable)`.
* Do not require site dependencies for base Riko installation.

## `wei-app`

* Existing component IDs remain valid through the compatibility exporter.
* Existing named filterers and sorters continue working initially.
* Existing components should not require rewrites in the first compatibility milestone.
* Canonical runtime/query fields may be added alongside legacy fields.

---

# 12. Explicit non-goals

Do not implement these during the initial sequence:

* a visual page builder;
* true Mithril DOM hydration;
* a two-way Riko/Lektor field synchronization engine;
* client-side AI execution;
* htpy fragments inside Lektor;
* htpy fragments inside Pelican;
* replacing the full `wei-app` SPA with islands;
* a general-purpose CMS;
* distributed artifact storage before the local-directory implementation works;
* async site rendering before sync contracts are stable;
* automatic publication of approval-required AI content.

---

# 13. Pull request sequence

Use small, reviewable pull requests.

## Riko

1. `export-target-registry`
2. `export-target-entry-points`
3. Any required generic module-registry fixes, isolated from site features

## `riko-site`

1. `site-domain-types`
2. `site-assembly-and-schema`
3. `site-modules`
4. `approval-store`
5. `mithril-wei-renderer`
6. `htpy-renderer`
7. `mithril-islands`
8. `django-adapter`
9. `asgi-adapters`
10. `lektor-exporter`
11. `pelican-exporter`
12. `staticjinja-exporter`

## `wei-app`

1. `generated-site-data`
2. `hybrid-content-snapshot`
3. `canonical-query-evaluator`
4. `mithril-island-loader`

Do not combine unrelated core refactors with renderer work.

---

# 14. Claude Code execution rules

For every phase:

1. Inspect current repository structure and conventions first.
2. Run baseline tests before editing.
3. State the exact files that will change.
4. Implement only the current phase.
5. Add or update tests in the same change.
6. Run formatting, linting, type checking, and tests using repository-configured commands.
7. Report:

   * files changed;
   * public APIs added;
   * compatibility impact;
   * test commands;
   * test results;
   * unresolved issues.
8. Do not silently change agreed architecture.
9. Do not invent a new framework abstraction when an agreed protocol already exists.
10. Do not add dependencies without explaining:

    * why they are needed;
    * whether they are optional;
    * how they affect the base installation.
11. Do not commit generated build output unless it is an explicit fixture.
12. Stop the phase when its acceptance criteria are met.

When implementation details conflict with the current repository, preserve the architectural intent and document the smallest necessary adaptation.

---

# 15. First Claude Code prompt

Begin with Phase 0 and Phase 1 only.

```text
You are implementing the first part of the Riko site-pipeline roadmap.

Repository:
- nerevu/riko
- base branch: features

Read the attached implementation gameplan in full.

Execute only:
- Phase 0: baseline and architecture records
- Phase 1: generic Riko export-target registry

Do not add any site-specific types or renderers yet.

Requirements:
1. Inspect the existing export implementation and current tests.
2. Run the existing test and type-check commands before making changes.
3. Introduce a generic ExportTarget protocol and ExportRegistry.
4. Adapt all existing conversion functions through compatibility wrappers.
5. Preserve every current export signature, return type, and file-writing behavior.
6. Add lazy entry-point discovery for the `riko.export_targets` group.
7. Preserve list_targets() behavior while including installed plugin targets.
8. Require replace=True for duplicate registrations.
9. Add characterization, regression, registry, and entry-point tests.
10. Do not add `.pipe(callable)`.
11. Do not modify pipeline lifecycle behavior.
12. Do not add a dependency on riko-site.

Before editing, provide:
- a short summary of the current export design;
- the files you plan to change;
- any compatibility hazards you identified.

After editing, provide:
- a concise implementation summary;
- the exact test and type-check commands run;
- the results;
- any remaining risks.

Stop after Phase 1 is complete.
```

After Phase 1 is reviewed and merged, proceed to the `riko-site` domain-types phase rather than asking Claude Code to implement the entire roadmap in one pass.
