# Artifact conversion gameplan

## 1. Mission

Define explicit boundaries for serialized format conversion, contact/card serialization,
template-driven reports, and rendered artifacts without turning Riko's record-stream core
into a document-rendering framework.

This plan extends the connector and orchestration gameplans: connectors acquire and deliver
bytes/records, Riko transforms records, and artifact/rendering extras turn finite data into
versioned files or reports.

In-memory Pandas/Arrow/Polars conversion is owned by `tabular-interop.md`; this plan owns
serialized codecs and artifact/rendering boundaries.

## 2. Inspiration integrated by this plan

The inspiration corpus contains a coherent family of conversion/report workflows:

* **pyconvert**: format inference/override, CSV/XLS/XLSX/DBF/MDB readers,
  CSV/JSON/GeoJSON/vCard writers, stdin/stdout, header sanitization, chunked processing.
* **csv2vcard**: configurable record-to-vCard mappings and chunked serialization.
* **contacts**: heterogeneous CSV/VCF contact exports and PII concerns.
* **csv2html**: CSV records rendered as a styled HTML table.
* **proposer**: YAML data + templates rendered to HTML/PDF/Markdown/PNG.
* **Carbone/CROO report generator**: source acquisition and transformation persisted as
  intermediate JSON, then Jinja/Markdown/HTML/PDF rendering; alternate DOCX-template
  renderer; rendering can be rerun without refetching source data.
* **HDX file proxy**: CSV/Excel resource acquisition converted into normalized records,
  with chunk limits.
* **Euler**: versioned tabular artifacts, offline/online sync, format conversion,
  reproducibility, and notification around versions.

The design lesson is to make representation boundaries explicit and durable.

## 3. Architectural rule

```text
source connector
    ↓
record stream
    ↓
Riko transformations
    ↓
explicit finite materialization boundary
    ↓
artifact codec / template renderer
    ↓
ArtifactRef
```

Never make HTML/PDF/DOCX rendering an implicit side effect of ordinary record iteration.

## 4. Artifact contract

Use a small immutable artifact reference:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ArtifactRef:
    uri: str
    media_type: str
    size: int | None
    fingerprint: str | None
    metadata: Mapping[str, JsonValue]
```

The artifact store owns bytes and lifecycle. Pipeline records carry references when an
artifact is too large or semantically better represented as a file/object.

## 5. Codec registry

Format support should be a registry of read/write capabilities rather than a monolithic
`convert()` switch:

```text
csv
json
ndjson
geojson
parquet (optional)
xlsx/xls (optional)
dbf/mdb (optional)
vcard (optional)
```

Each codec declares:

```text
media types
extensions
read/write support
streaming/chunk support
schema/metadata behavior
optional dependencies
```

Arrow is an in-memory interchange type rather than an artifact format contract here;
Arrow frame/table conversion is specified in `tabular-interop.md`. Arrow IPC/Feather, if
added as serialized codecs, belong in this registry like Parquet.

Extension inference is convenience; explicit media type/codec wins.

## 6. Source and destination inference

Borrow pyconvert's useful UX while avoiding ambiguity:

```text
explicit codec/media type
→ Content-Type / connector metadata when trustworthy
→ file extension
→ bounded content sniffing only when explicitly allowed
```

Do not redownload remote content to determine type. Reuse connector response metadata/body
as specified in `connectors.md`.

## 7. Streaming versus materializing codecs

A codec declares whether it can operate incrementally.

Examples:

```text
CSV/NDJSON       naturally streaming
JSON array       may require structured streaming parser or materialization
XLSX             finite workbook boundary
Parquet          finite/row-group artifact boundary
PDF/PNG          terminal rendered artifact
```

Chunk size is explicit for large finite inputs. A codec cannot silently consume a known
unbounded stream.

Generic frame batching/chunk semantics are owned by `tabular-interop.md`; codecs only
declare how their serialized representation can be read/written incrementally.

## 8. Header and field normalization

Useful pyconvert behavior becomes explicit transforms rather than format-specific magic:

```python
flow.normalize_fields(conf={"case": "snake", "dedupe": True})
```

Codec readers may report duplicate/invalid headers, but canonical renaming belongs to a
normal Riko transform so it is observable and reusable.

## 9. Declarative record mapping

vCard/report outputs often require destination-specific field mapping.

Support a bounded expression/mapping vocabulary:

```python
mapping = {
    "given_name": {"field": "first_name"},
    "family_name": {"field": "last_name"},
    "organization": {"field": "company"},
}
```

Allow constants and approved transformations, but do not load arbitrary Python lambdas from
serialized workflow definitions. Python callers can still use callable pipes before the
serializer.

## 10. vCard/contact output

A contact serializer is an optional codec/sink:

```text
records
→ validated contact mapping
→ vCard stream/artifact
```

Requirements:

* repeated phone/email fields are represented correctly;
* Unicode is preserved;
* escaping/folding follows the selected vCard version;
* source PII classification/provenance is retained in artifact metadata where useful;
* no contact values are copied into routine diagnostic logs.

Contact-domain normalization (e.g. international phone formatting) is an explicit transform,
not hidden serializer behavior unless mandated by the vCard standard.

## 11. Standard output / standard input

CLI codecs should preserve the composability demonstrated by pyconvert/csv2vcard:

```text
stdin → decode → Riko → encode → stdout
```

Binary formats require binary-safe handling and should not be accidentally emitted to a
TTY without an explicit output path/flag.

## 12. Tabular frame boundary

This plan intentionally does not define `from_pandas`, `to_pandas`, `from_arrow`,
`to_arrow`, Arrow batch semantics, Polars helpers, null coercion, or DataFrame index rules.
Those contracts live in `tabular-interop.md`.

Artifact codecs compose with those boundaries when useful:

```text
Pandas/Arrow/Polars     record stream       serialized artifact
        ↕                    ↕                     ↕
  tabular-interop  ←→   Riko transforms  ←→  artifact codecs
```

A Parquet/XLSX/CSV implementation may internally use Arrow or another frame library, but
that is an adapter implementation detail rather than a second public frame API.

## 13. Template rendering

Report rendering is an optional service consuming a finite context object and templates:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class RenderPlan:
    template: ArtifactRef
    context: ArtifactRef | JsonValue
    output_media_type: str
    renderer: str
    options: Mapping[str, JsonValue]
```

Potential renderers are adapter implementations:

```text
Jinja + Markdown → HTML
HTML → PDF (browser/WeasyPrint adapter)
DOCX-template/Carbone-style renderer
HTML → PNG
Markdown
```

Riko core does not depend on Chromium, WeasyPrint, LibreOffice, or Carbone.

## 14. Separate data preparation from presentation

The CROO reporting pipeline shows an important reproducibility boundary:

```text
fetch Airtable data
→ normalize/aggregate
→ parsed report data artifact
→ render template
→ HTML/PDF artifacts
```

The parsed report context should be durable and fingerprinted. Editing a template should
allow rendering to rerun without refetching or recomputing upstream data when the context
artifact is unchanged.

This is preferable to a renderer reaching back into source connectors itself.

## 15. Report context

A report context is ordinary serializable data with provenance:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ReportContext:
    data: JsonValue
    inputs: tuple[ArtifactRef, ...]
    generated_at: datetime
    pipeline_fingerprint: str
```

Large tabular sections may be referenced by artifact rather than embedded in one giant JSON
object.

## 16. Template/version fingerprinting

Rendered output fingerprints depend on at least:

```text
context fingerprint
template fingerprint
renderer/version
render options
```

Record these inputs so a report can be reproduced and so `if_changed` sinks can avoid
republishing identical artifacts.

## 17. Multi-format reports

A single prepared context may feed several render plans:

```text
                 ┌→ Markdown
report context ──┼→ HTML
                 ├→ PDF
                 └→ DOCX/PNG via optional renderer
```

This is fan-out over artifacts, not four repeated source/data-processing pipelines.
Fan-out mechanics remain owned by `fanout-topology.md`.

## 18. Rendered tables

CSV-to-HTML is a special case of:

```text
records
→ finite table materialization
→ table model
→ HTML/Markdown renderer
```

A general table renderer should not contain application-specific column names such as the
legacy eBay LEGO mapping. Column selection/formatting belongs in configuration or upstream
transforms.

If the intermediate table is a Pandas/Arrow value, its conversion semantics come from
`tabular-interop.md`.

## 19. Artifact publishing and versioning

Borrow the useful part of Euler's vision without turning Riko into Dropbox/Git:

* every durable output may carry a content fingerprint/version ID;
* publishing can use `always`, `if_changed`, or provider-native version semantics;
* lineage links output to input artifacts and pipeline/template fingerprints;
* external catalog/index systems may consume artifact metadata;
* notifications about a new version are ordinary monitoring/fan-out actions.

Provider-specific idempotent write mechanics remain owned by `provider-integrations.md`.
Offline synchronization/conflict resolution is outside Riko core.

## 20. Artifact metadata and provenance

Useful metadata includes:

```text
media type
encoding
row/record count where known
schema fingerprint
content fingerprint
created time
source artifact IDs
pipeline/run ID
template/renderer fingerprints
sensitivity classification
```

Avoid embedding full data payloads in metadata solely for convenience.

## 21. Security

Requirements:

* template paths/URIs are policy-checked;
* remote images/resources are disabled or explicitly allowed during HTML/PDF rendering;
* browser renderers use bounded time/memory and isolated contexts;
* untrusted template execution cannot import arbitrary Python;
* PII artifacts inherit appropriate sensitivity metadata;
* output paths cannot escape configured roots through traversal;
* secret values are not rendered unless explicitly supplied as approved context.

## 22. CLI surface

Potential commands:

```text
riko convert input.csv output.json
riko convert - --from csv --to ndjson
riko render report-context.json template.md report.pdf
riko artifact describe <ref>
```

CLI convenience resolves to the same codec/render services used by Python and serialized
workflow definitions.

Frame-specific CLI behavior, if ever added, should call `tabular-interop.md` contracts
rather than add independent coercion rules here.

## 23. Testing strategy

Contract tests include:

1. explicit codec beats extension inference;
2. CSV/NDJSON stream without full materialization;
3. known-unbounded stream refuses terminal workbook/PDF materialization;
4. Unicode and duplicate field names round-trip predictably;
5. declarative vCard mapping generates valid deterministic fixtures;
6. arbitrary callable/import references are rejected from serialized mapping;
7. stdin/stdout text conversion is binary-safe and deterministic;
8. report context is reusable across multiple renderers;
9. template-only change rerenders without upstream acquisition;
10. artifact fingerprint changes on context/template/renderer changes;
11. `if_changed` publishing suppresses identical artifact writes through the shared sink
    policy;
12. remote-resource access during rendering follows policy;
13. PII metadata is retained and sensitive fields are not logged;
14. renderer optional-dependency failure is explicit.

Pandas/Arrow/Polars conversion tests live in `tabular-interop.md`.

## 24. Phases

```text
AC0  ArtifactRef + codec capability metadata
AC1  streaming CSV/JSON/NDJSON codecs
AC2  optional XLS/XLSX/DBF/MDB/vCard/Parquet codecs
AC3  declarative destination mappings
AC4  ReportContext + RenderPlan
AC5  Jinja/Markdown/HTML renderer
AC6  optional PDF/DOCX/PNG render adapters
AC7  fingerprints, lineage, and if-changed publishing integration
AC8  CLI convert/render/describe
```

Frame interoperability has its own phases in `tabular-interop.md`.

## 25. Definition of done

1. Serialized format conversion is an explicit source/sink boundary, not scattered utility
   code.
2. Streaming formats remain lazy/chunked where practical.
3. Terminal renderers cannot accidentally consume unbounded streams.
4. Optional legacy/business formats do not become core dependencies.
5. Serialized mappings cannot execute arbitrary Python.
6. Prepared report data can be persisted and rerendered independently of acquisition.
7. Multi-format output reuses one report context.
8. Artifacts are fingerprinted and lineage-aware.
9. PII and renderer security boundaries are explicit.
10. Pandas/Arrow/Polars contracts are referenced from `tabular-interop.md`, not duplicated
    here.
