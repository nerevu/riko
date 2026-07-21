# Shelf Integration Review

## Result

The Shelf material has been incorporated into revised copies of every attached gameplan
and five new authoritative gameplans. The original files are unchanged.

## Mapping

| Shelf section | Destination | Treatment |
|---|---|---|
| Milestone 7: column transforms | `productionizing.md`, `enrichment-modules.md` | Promote `coalesce`, `strtransform`, and explicit `dropfields`; keep existing `regex`/`rename`; reject public `applys` and standalone `strip`. |
| Milestone 5.1: SQL source | `database-transforms.md` | Move to `riko-sql`; Ibis-backed batch reads, named connections, explicit write target. |
| Milestone 5.2: DataFrame source | `productionizing.md` | Use `from_frame()` or an execution-resource reference; never serialize a frame object in `conf`. |
| Milestone 6: fetchpage | `productionizing.md`, `connectors.md`, `riko-site.md` | Add response envelope and metadata; keep extraction as downstream named modules; reject `postprocess` in serialized config. |
| Milestone 9: msgspec | `productionizing.md`, `connectors.md` | Add a codec protocol and benchmarks; keep mappings canonical; optional msgspec implementation at serialization boundaries only. |
| Milestone 11: FTP/SFTP/IMAP/SMTP/brokers | `connectors.md`, `agents.md`, `azure-automation.md`, `twisted-protocol-servers.md` | Extension adapters with AnyIO, execution-scoped resources, delivery semantics, and credential references; reject Twisted *as runtime*, but bridge Twisted *protocol* impls via `asyncioreactor` where genuinely superior (server-side). |
| Milestone 12: universal fetch | `connectors.md`, `repo-refinement.md`, `cli.md` | Registry-backed `SourcePlan`; staged migration from RSS `fetch`; explicit bounded probing; no hard-coded monolith. |
| Milestone 13.1: Singer | `connectors.md`, `productionizing.md` | Implement as Singer↔RDP adapter so schema and state are preserved. |
| Milestones 13.2-13.3: webhooks/feedtail | `orchestration.md`, `agents.md` | Webhook ingress and finite feed polls with durable checkpoints; not an in-memory forever source. |
| Milestone 13.4: SaaS auth/proxy | `mcp.md`, `connectors.md`, `ai-Inference.md` | Token service becomes credential provider; proxy becomes OpenAPI provider; no special core module. |
| Milestones 13.5, 13.8, 13.9 | `connectors.md` | Optional tabular, CKAN, and Prometheus adapters. |
| Milestones 13.6-13.7 | `enrichment-modules.md` | Optional bounded near-duplicate and contact-extraction modules with explicit failure behavior. |
| Milestone 15: orchestration | `orchestration.md`, `cli.md` | One Riko run per task by default; split only at durable boundaries; CLI is not a scheduler. |
| Milestones 19-20: Ibis/dbt | `database-transforms.md`, `repo-refinement.md` | Separate `riko-sql` and `riko-dbt`; Arrow batch bridge, inspectable push-down, explicit SQL export target, durable dbt boundary. |

## Major corrections applied

1. AnyIO remains the only async **runtime**; Twisted is not promoted as a runtime. Runtime and
   protocol layers are orthogonal (ROADMAP §23.1): Twisted *protocol* implementations may be
   bridged onto the asyncio loop via `asyncioreactor` inside an adapter where genuinely superior
   (chiefly server-side — see [twisted-protocol-servers.md](twisted-protocol-servers.md)).
2. Passwords, tokens, and private keys are references, never URI user-info or serialized
   configuration values.
3. DataFrame objects are runtime resources, not declarative JSON.
4. Fetching, content extraction, and transformation remain separate stages.
5. Source resolution is inspectable and separate from network execution.
6. A universal source entry point cannot silently repurpose the existing RSS `fetch`
   module during the current compatibility window.
7. Orchestrators wrap complete pipeline runs or durable subgraphs, not every lazy stage.
8. Singer compatibility passes through RDP schema/state contracts.
9. Database writes are explicit sink/export operations, not a hidden source-module mode.
10. Optional enrichment dependencies fail clearly rather than silently doing nothing.

## Files

Revised existing plans:

```text
agents.md
ai-Inference.md
azure-automation.md
cli.md
dotdict-parsing.md
mcp.md
module-documentation.md
productionizing.md
repo-refinement.md
riko-site.md
```

New plans:

```text
connectors.md
orchestration.md
database-transforms.md
enrichment-modules.md
twisted-protocol-servers.md
```
