# AI/ML strategy assessment

This namespace is non-authoritative. It keeps an external AI/ML strategy assessment of
the roadmap as prior art. The actionable owners are the gameplans linked from the
dispositions below; the assessment's rankings, package proposals, and sequence are
recommendations, not commitments.

## Triage dispositions (2026-11-24)

1. **Already-planned techniques** (LLM/SLM inference, embeddings, reranking, model
   routing/cost optimization, summarization, bounded decomposition, agentic loops,
   rule/policy evaluation): no action. Owned by
   [ai-inference.md](../gameplans/ai-inference.md) § 2, § 9, § 18, and AI0–AI11;
   [agents.md](../gameplans/agents.md) § 7; [mcp.md](../gameplans/mcp.md) policy; and
   [feed-monitoring.md](../gameplans/feed-monitoring.md) M10.
2. **Misattributions in assessment § 2**: rejected. Semantic retrieval is not an MCP
   concern ([mcp.md](../gameplans/mcp.md) § 18: semantic indexing/retrieval belongs in
   riko-ai), and [performance.md](../gameplans/performance.md) owns no runtime
   semantics, so regression/change-point statistics do not belong there.
3. **Online ML / River**: the core ban on ML anomaly models is narrowed to "core takes
   no ML/numerical-library dependency and hosts no hidden model state". Learned scorers
   plug into M9 as Resource-supplied scorers with `StateStore`-backed state, River as
   the first optional adapter outside core:
   [feed-monitoring.md](../gameplans/feed-monitoring.md) § 15.1 (M9a).
4. **Streaming statistics beyond M9**: EWMA, modified z-score, quantile estimation, and
   change-point detection join M9's deterministic methods in
   [feed-monitoring.md](../gameplans/feed-monitoring.md) § 15. No separate
   `statistical-analysis.md`.
5. **Entity resolution**: new owner
   [entity-resolution.md](../gameplans/entity-resolution.md). Domain precedence stays in
   [monthly-dashboard.md](../gameplans/monthly-dashboard.md) § 6, the `simhash` module
   in [enrichment-modules.md](../gameplans/enrichment-modules.md) § 8, and the
   advisory-only rename rule in [highergov-feed.md](../gameplans/highergov-feed.md).
6. **`machine-learning.md` / `riko-ml`**: deferred to P14 (extensions outside core).
   Trigger: several integrations need shared model lifecycle, prediction, persistence,
   and evaluation contracts (assessment § 6). Until then, adapters such as River ship
   as optional extras or single-purpose ecosystem packages.
7. **Long tail** (classical ML, time-series forecasting, mathematical optimization,
   graph algorithms/GNNs, bandits, custom deep learning, GANs/diffusion): recorded here
   only; no owner.
8. **This assessment**: kept here as non-authoritative research.

## Assessment

Riko should prioritize **applied AI inference, lightweight statistical learning,
semantic retrieval, and controlled agentic automation**, rather than becoming a
general-purpose machine learning or model-training framework.

Having reviewed the `next` branch's roadmap and relevant gameplans, I see five major
areas where AI and ML can advance Riko's objectives:

- **Data automation:** enrichment, entity resolution, classification, extraction and
  data quality.
- **IT automation:** anomaly detection, configuration drift, cybersecurity assessment
  and remediation.
- **Intelligent automation:** capability discovery, tool selection, task planning and
  verification.
- **Digital experience automation:** content extraction, summarization, generation and
  publishing.
- **Runtime optimization:** historical execution analysis, model selection and cost
  optimization.

The existing architecture is well positioned for these because pipelines, state,
batching, resources, provenance, caching and effects are useful across virtually all AI
model families.

### 1. Recommended priorities

| Rank | Technique | Riko application | Priority |
| ---- | --------- | ---------------- | -------- |
| 1 | LLMs and SLMs | Extraction, enrichment, structured inference, classification | Critical |
| 2 | Embedding models | Semantic search, capability discovery, entity matching | Critical |
| 3 | Statistical methods | Feed monitoring, anomalies, thresholds, data quality | Critical |
| 4 | Symbolic AI / rule engines | Policy, compliance, verification, controlled execution | Critical |
| 5 | Reasoning models | Task decomposition, research, complex capability selection | High |
| 6 | Agentic AI | Bounded autonomous workflows and tool orchestration | High |
| 7 | Probabilistic record linkage | Deduplication, reconciliation, asset identity | High |
| 8 | Classical ML | Classification, regression, risk scoring | Medium-high |
| 9 | Online machine learning | Incremental learning from streams | Medium-high |
| 10 | Time-series models | Forecasting, trend detection, capacity planning | Medium |
| 11 | Mathematical optimization | Model routing, scheduling, resource allocation | Medium |
| 12 | Graph algorithms and GNNs | Entity relationships, dependency and security analysis | Medium-low |
| 13 | Reinforcement learning / bandits | Adaptive model and capability selection | Low |
| 14 | LSTM, GRU, CNN and custom neural networks | Specialized predictive workloads | Low |
| 15 | GANs and diffusion models | Media generation and synthetic data | Low |

These priorities are recommended additions and emphasis, not the existing implementation
sequence.

### 2. Where each technique fits into the gameplans

| Gameplan | AI/ML techniques to prioritize |
| -------- | ------------------------------ |
| ai-inference.md | LLMs, SLMs, embeddings, reranking, model optimization |
| agents.md | Reasoning models, symbolic reasoning, bounded planning |
| mcp.md | Semantic retrieval, capability classification and ranking |
| feed-monitoring.md | Rolling statistics, anomaly detection, online learning extensions |
| enrichment-modules.md | Fuzzy matching, probabilistic linkage, classification |
| operations-as-code.md | Rule-based reasoning, drift detection, LLM-assisted planning |
| microsoft-administration.md | Policy evaluation, anomaly detection, risk scoring |
| monthly-dashboard.md | Entity resolution, regression, forecasting |
| riko-site.md | Generative AI, summarization, semantic classification |
| performance.md | Regression, change-point detection, statistical benchmarking |

### 3. Specific algorithms worth prioritizing

**Statistical learning and monitoring** (high value, low implementation complexity):
rolling mean and variance; z-score and modified z-score; exponentially weighted moving
average (EWMA); linear regression / least squares; quantile estimation; change-point
detection.

**Similarity and entity resolution** (integration and reconciliation): Levenshtein and
Jaro-Winkler distance; MinHash and locality-sensitive hashing; TF-IDF and BM25; cosine
similarity; Fellegi–Sunter probabilistic linkage; semantic embeddings.

**Classical machine learning** (structured data, predictive analytics): linear and
logistic regression; gradient-boosted trees; isolation forest; k-means and HDBSCAN;
naive Bayes.

**Incremental and online learning** (strong architectural alignment): stochastic
gradient descent; online linear and logistic regression; Hoeffding trees; half-space
trees; Adaptive Windowing (ADWIN); incremental clustering.

**Foundation models**: small and large language models; text and multimodal embeddings;
cross-encoder reranking; multimodal models; reasoning models; retrieval-augmented
generation.

### 4. Online machine learning is the largest underexplored opportunity

The existing AI gameplan is heavily focused on generative inference. Given Riko's
streaming architecture, online machine learning deserves investigation. Batch learning
collects data, trains, deploys, and periodically retrains. Online learning predicts and
incrementally updates as records arrive.

| Riko capability | Online ML application |
| --------------- | --------------------- |
| Pipeline | Incremental feature processing |
| StateStore | Persisting model state |
| Checkpoints | Resuming model updates |
| Resources | Loading and managing estimators |
| Loop | Continuous learning iterations |
| Batch | Mini-batch training |
| Cache | Reusing predictions for fixed model versions |
| Publish/subscribe | Distributing predictions and alerts |
| Events | Monitoring accuracy and drift |
| Provenance | Tracking model inputs and versions |

Potential applications: abnormal login activity, unusual procurement opportunities,
endpoint behavior, adaptive risk scores, changes in API response patterns. River
(<https://riverml.xyz/>) is the primary integration candidate.

Constraint noted by the author: feed-monitoring excluded ML anomaly models from Core, so
online learning should be an ecosystem extension, not an expansion of the Core contract.

### 5. Libraries Riko should leverage

| Library | Purpose | Priority |
| ------- | ------- | -------- |
| River (<https://riverml.xyz/>) | Online ML, streaming statistics, drift detection | High |
| scikit-learn (<https://scikit-learn.org/>) | Classical ML and preprocessing | High |
| RapidFuzz (<https://github.com/rapidfuzz/RapidFuzz>) | Fast fuzzy matching | High |
| Splink (<https://github.com/moj-analytical-services/splink>) | Probabilistic record linkage | High |
| Sentence Transformers (<https://www.sbert.net/>) | Local embeddings and reranking | High |
| ONNX Runtime (<https://onnxruntime.ai/>) | Portable pretrained model inference | High |
| statsmodels (<https://www.statsmodels.org/>) | Statistical modeling | Medium |
| LightGBM (<https://github.com/microsoft/LightGBM>) | Structured data predictions | Medium |
| StatsForecast (<https://github.com/Nixtla/statsforecast>) | Statistical forecasting | Medium |
| OR-Tools (<https://developers.google.com/optimization>) | Mathematical optimization | Medium |
| NetworkX (<https://networkx.org/>) | Graph analytics | Medium |
| PyTorch (<https://pytorch.org/>) | Specialized deep learning | Low |

Riko should own the execution and integration contracts, not the underlying numerical
algorithms.

### 6. Proposed ecosystem architecture

```text
Applications: cybersecurity · data analytics · IT automation · publishing
riko-ai: LLMs, embeddings, reasoning, retrieval, planning
riko-ml (proposed): classical ML, online learning, forecasting, model inference
riko-mcp: capability discovery, validation, controlled execution
Other integrations: providers, SQL, Connect, Site, Microsoft
Riko Core: Pipeline · Workflow · State · Resources · Events · Cache · Effects · Batch · Loop
```

ML integrations start as optional extensions. A dedicated `riko-ml` package becomes
justified once multiple integrations require common model lifecycle, prediction,
persistence and evaluation contracts.

- **Core:** executes data and computation workflows.
- **AI:** generative inference, semantic understanding and reasoning.
- **ML:** predictive, statistical and adaptive learning.
- **MCP:** discovers, validates and executes external capabilities.

### 7. Recommended implementation sequence (ecosystem, not the R-track)

1. Statistical and deterministic foundations: rolling statistics, anomaly rules, change
   detection, fuzzy matching, record reconciliation.
2. Generative inference: AI0–AI2 of the inference gameplan.
3. Semantic retrieval: embeddings, keyword search, hybrid retrieval, reranking,
   capability selection.
4. Predictive and online ML: scikit-learn and River integrations, pretrained model
   inference, checkpointable estimators, drift detection.
5. Intelligent automation: bounded task decomposition, agent workflows, verification,
   approval, recovery.
6. Adaptive optimization: historical model evaluation, predictive routing, cost
   optimization, eventually multi-armed bandits if evaluation data suffices.

### 8. Strategic assessment (qualitative fit)

| Area | Fit |
| ---- | --- |
| Deterministic reasoning | 5/5 |
| LLM inference | 5/5 |
| Semantic retrieval | 5/5 |
| Statistical stream analysis | 5/5 |
| Entity resolution | 5/5 |
| Online ML | 4.5/5 |
| Agentic AI | 4.5/5 |
| Classical ML | 4/5 |
| Time-series forecasting | 3.5/5 |
| Mathematical optimization | 3/5 |
| Custom deep learning | 2/5 |
| Reinforcement learning | 1.5/5 |
| Foundation model training | 1/5 |

Proposed gameplans: `machine-learning.md` (model adapters, prediction, incremental
learning, artifacts, evaluation), `entity-resolution.md` (deterministic, fuzzy,
probabilistic, semantic record linkage), `statistical-analysis.md` (streaming
statistics, regression, forecasting, statistical anomaly detection). Each should consume
existing runtime contracts rather than introduce parallel execution, state or resource
systems.

Positioning: a unified data and intelligent automation engine composing deterministic
logic, statistical algorithms, classical ML and modern AI within the same reproducible
workflow, which is more durable than another LLM orchestration framework.

Caveat from the author: based on the roadmap and selected gameplans on `next`, not a
complete implementation audit or empirical benchmark; the ML package, gameplans and
rankings are recommendations, not commitments.
