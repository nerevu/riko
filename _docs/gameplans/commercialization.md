# Commercialization gameplan

## 1. Mission

Document how the **Riko ecosystem** can create commercial value without changing the scope or
licensing expectations of Riko Core.

Riko Core remains the configurable pipeline engine. Commercial products, managed services,
provider packs, Operations as Code tooling, hosted control planes, training, and vertical solutions
may be built **on** Core, but this plan does not make those products part of the `riko` package or
turn roadmap ideas into shipped product promises.

This plan exists so architectural work can preserve useful commercial seams while technical
gameplans remain authoritative for implementation contracts.

Related authoritative plans:

* `execution-semantics.md` — Core Pipeline/Context/execution/state/identity semantics;
* `extensibility.md` — plugins, workflow serialization, adapter packages, and ecosystem seams;
* `provider-integrations.md` — provider adapters and provider-specific import/export hooks;
* `operations-as-code.md` — Git-first operations, planning, deployment drift, import/normalization,
  compatibility, and migration semantics;
* `orchestration.md` — external scheduling/runners and durable run boundaries;
* `mcp.md` — capability catalog, execution policy, and approval;
* `azure-automation.md` / `microsoft-administration.md` — Microsoft execution and administration;
* `rdp-connect.md` — data-integration protocol/Connect direction;
* `riko-site.md` — framework-neutral site generation;
* `ai-inference.md` / `agent-scenarios.md` — AI and bounded agent-oriented workflows.

## 2. Ownership boundary

This plan owns **commercial strategy vocabulary and packaging hypotheses only**:

```text
commercial product families
service-led adoption motions
managed/hosted product opportunities
vertical solution packaging
small-nonprofit service tiers
training/support/partner strategies
commercial validation gates
```

It does not own or redefine:

```text
Pipeline / Context / execution             execution-semantics.md
OperationSpec / OperationPlan              operations-as-code.md
CapabilityInfo / CapabilityPlan / policy   mcp.md
provider import/export mechanics           provider-integrations.md
scheduling / runners                       orchestration.md
Microsoft ChangePlan                       microsoft-administration.md
site model / SiteSpec                      riko-site.md
technical implementation order             implementation-sequence.md
```

Commercial language must not be used to bypass those boundaries. A feature is not a technical
promise merely because it is commercially attractive.

## 3. Commercial architecture

The preferred model is analogous to successful developer-infrastructure ecosystems: keep the engine
useful and independently adoptable, then monetize the organizational layer around it.

```text
Riko Core
    configurable Pipeline engine
        ↓
ecosystem packages
    Connect / providers / Microsoft / MCP / AI / Site / Operations as Code
        ↓
commercial delivery
    managed services / operation packs / support / hosted control plane / private runners
        ↓
vertical products
    MSP / nonprofit / public-sector / data / digital-experience offerings
```

The important boundary is that **Core powers the outcomes; Core is not the entire commercial
product**.

A commercial control plane should normally treat Git/version-controlled definitions as canonical
when Operations as Code is in use. The control plane can manage collaboration, policy, approvals,
runs, evidence, environments, and deployment status without becoming the authoring source of truth.

## 4. Primary product families

The current strategic product families are:

### Nerevu Data Automation

Built primarily from Core, Connect/RDP, connectors/providers, transformations, artifacts, and
orchestration. Candidate outcomes include managed data pipelines, integrations, reporting hubs,
data migration/enrichment, monitoring, and embedded data-processing services.

### Nerevu IT Automation

Built primarily from Core, provider integrations, Microsoft adapters/administration, Operations as
Code, monitoring, and orchestration. Candidate outcomes include managed Microsoft/Google standards,
employee/device lifecycle automation, compliance evidence, security-posture reporting, and
repeatable MSP operations.

### Nerevu Intelligent Automation

Built primarily from Core, MCP/capabilities, AI inference, agent scenarios, policy, and approval.
The commercial distinction is controlled automation: AI may propose/select/interpret while
validated capabilities, policy, approval, deterministic execution, and verification remain
separate.

### Nerevu Digital Experience Automation

Built primarily from Core, `riko-site`, Connect/providers, artifacts, and optional AI enrichment.
Candidate outcomes include managed data-driven websites, public program/resource directories,
automated publishing, document/data experiences, and integrated reporting.

These names are working strategy labels, not package names or Core API commitments.

## 5. MSP client-facing opportunities

Riko can support client-visible managed products rather than remaining invisible automation behind
helpdesk work. Candidate offerings include:

* a client operations portal spanning users, devices, licenses, backups, security, service health,
  and open actions;
* compliance-evidence and security-posture reporting with verified remediation history;
* managed Microsoft 365 or Google Workspace standards and identity/access reviews;
* employee onboarding/offboarding and device-provisioning operations;
* a client automation catalog exposing approved, policy-controlled operations;
* executive technology briefings, lifecycle/budget planning, and incident-readiness packs;
* managed reporting/data hubs across operational systems;
* managed website/data services and AI-assisted publishing;
* grant/program reporting automation for nonprofit and public-sector clients.

The common commercial value is not "Riko automation" as a feature. It is a repeatable managed
outcome implemented with shared Riko contracts.

## 6. Operations as Code commercial motion

Operations as Code creates several adoption and monetization paths while remaining an ecosystem
capability rather than a Core promise.

### Managed collaboration/control plane

Potential paid capabilities include repository/environment views, plan history, approvals,
execution history, operation-version deployment status, automation drift, evidence retention,
policy/governance, observability, and secret-provider integration.

### Private and customer-hosted runners

Regulated or private environments may execute approved operations on customer/MSP-controlled
runners while a hosted service coordinates metadata and policy. Runner semantics remain technical
concerns of the operations/orchestration/provider plans rather than this commercial plan.

### Operation and provider ecosystem

Reusable operation packs, certified integrations, private catalogs/registries, provider packs, and
vendor-sponsored integrations can become commercial distribution channels. Technical registration
and compatibility contracts remain in their owning gameplans.

### Migration and automation portability

Automation-estate assessment and migration are strategic adoption levers:

```text
inventory proprietary automations
→ preserve source artifacts
→ normalize where semantics are known
→ report target compatibility/lossiness
→ migrate approved operations
→ establish Git/version control as the future source of truth
```

This can support RMM-to-RMM, workflow-platform-to-runner, or vendor-library-to-Git migrations.
**Portability is a goal and assessment result, not a promise that every vendor artifact has a
lossless equivalent.** `operations-as-code.md` owns that technical honesty requirement.

### Services, support, and education

Potential revenue channels include Operations as Code assessments, implementation/migration
projects, managed deployment, enterprise support/LTS, architecture advisory services, workshops,
training, and later certification. Workshops are useful early because the methodology can be taught
before every hosted/product feature exists.

### Enterprise governance and evidence

Policy, approvals, private runners, audit evidence, retained run history, SSO/organization controls,
and controlled deployment are natural enterprise layers. They consume technical policy/evidence
contracts; this plan does not define another policy engine.

### Partnerships and embedding

Vendor-sponsored providers, certified integrations, marketplace partnerships, OEM/embedded use,
and supported distributions may extend reach. Riko Core's open licensing should remain compatible
with independent embedding; commercial value should come from maintained ecosystem/services rather
than artificial restrictions on Core.

## 7. Small-nonprofit strategy: MissionOps

A particularly good vertical is the small, volunteer-led or lightly staffed nonprofit that needs a
professional digital operating environment but cannot justify separate IT, data, web, and systems
teams.

The working service concept is **MissionOps**:

```text
website
+ Microsoft 365 or Google Workspace administration
+ identity/security basics
+ donor-system integration
+ volunteer management/integration
+ forms and workflow automation
+ reporting
+ support/advisory
```

The strategy is integration-first. Do not build a donor CRM or volunteer platform merely because
Riko can process the data. Prefer established systems when they fit, and use Riko to normalize,
integrate, automate, report, and publish across them.

Likewise, Microsoft 365 and Google Workspace are supported operating environments, not competing
Riko products. BYOD-heavy organizations may remain on Google Workspace or a lightweight Microsoft
configuration; organization-owned-device maturity can trigger stronger endpoint-management
options later.

### Tier 1 — Essential: "Keep us running"

For very small organizations that primarily need a competent administrator and basic governance.
Typical scope:

* Microsoft 365 or Google Workspace administration;
* accounts, aliases, groups, and routine access changes;
* MFA/security baseline and admin-role review;
* basic shared-drive/site organization guidance;
* routine technical support and basic AI/Gemini/Copilot use guidance;
* periodic account/security review.

### Tier 2 — Operations: "Help us operate better"

For organizations ready to structure board/staff collaboration and automate routine work.
Typical scope adds:

* shared-drive/folder architecture and board/committee collaboration structure;
* shared calendars, role-based groups, and governance conventions;
* practical BYOD guidance;
* onboarding/offboarding workflows;
* approved AI-assisted board/operations workflows;
* lightweight contact/volunteer forms and basic automations;
* periodic technology/operations review.

### Tier 3 — MissionOps: "Run our digital operations"

For organizations that want one partner to operate the connected digital environment. Typical
scope adds:

* managed website support and data-driven publishing where appropriate;
* donor and volunteer system integrations;
* website forms/workflows;
* organizational reporting/dashboarding;
* cross-system integrations and a maintained catalog of standard automations;
* recurring operational review and technology roadmap.

Large website redesigns, major migrations, custom applications, substantial data remediation, and
bespoke integrations remain project work rather than being silently absorbed into a recurring tier.

## 8. Nonprofit data and automation opportunities

MissionOps can converge fragmented operational data without requiring a monolithic replacement
system. Useful canonical business concepts include people/organizations, donors/donations,
campaigns, volunteers/activities, programs, events, grants, documents, interactions, and form
submissions. The technical schemas belong to future vertical packages, not this strategy plan.

High-value standard operations include staff onboarding/offboarding, donor acknowledgements,
volunteer intake, volunteer-hours reporting, contact routing, staff/board directory synchronization,
content-to-newsletter drafts, and recurring leadership reports.

A managed website is especially valuable when it becomes an output of the same operating data:
programs, staff, events, resources, impact metrics, donations, volunteer opportunities, and news can
flow through reviewed pipelines into `riko-site` rather than being maintained as disconnected copies.

## 9. Public-sector and nonprofit expansion

The same ecosystem can support larger public-sector/nonprofit engagements around digital
modernization, accessibility-aware web publishing, compliance evidence, managed Microsoft
administration, data/reporting infrastructure, grant/program reporting, monitoring, and integration.
Vertical packs should encode repeatable domain knowledge while keeping customer-specific policy and
credentials outside reusable source definitions.

## 10. Commercial validation gates

Before describing a future strategy as a mature product, require evidence appropriate to the claim:

```text
working technical contract in the authoritative gameplan/package
production-quality provider coverage for the target use case
repeatable deployment and verification
security/redaction/policy tests
documentation and upgrade path
real customer/internal operating evidence
supportable observability and failure handling
```

A hosted control plane additionally needs tenancy isolation, identity/access management, evidence
retention policy, runner security, billing/entitlement design, and operational support. Those are not
requirements for Riko Core itself.

## 11. Commercial sequencing

A pragmatic sequence is:

```text
C0  Nerevu internal dogfooding + client-specific managed automations
C1  repeatable service packs, assessments, workshops, and migrations
C2  maintained operation/provider packs + managed Operations as Code
C3  collaboration/control-plane features, private runners, governance, evidence
C4  enterprise support, partner/certified ecosystem, training/certification
C5  broader OEM/embedded and marketplace distribution where validated
```

This sequence is commercial, not the technical implementation dependency graph.
`implementation-sequence.md` remains authoritative for implementation order.

## 12. Definition of done

1. Riko Core remains independently useful and is not redefined as the commercial platform.
2. Ecosystem product families map cleanly to technical owners rather than inventing parallel APIs.
3. Operations as Code supports commercial migration/governance opportunities without promising
   universal lossless portability.
4. MSP offerings are expressed as client outcomes, not as a list of internal Riko features.
5. The small-nonprofit strategy retains the Essential, Operations, and MissionOps maturity tiers
   without embedding transient pricing in architecture docs.
6. Commercial plans can evolve without forcing changes to Core runtime contracts.
