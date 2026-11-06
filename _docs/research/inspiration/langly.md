---
source: ../../../../langly/readme.md
---

# langly

A CLI for running and evaluating multi-agent AI workflows built on
[LangGraph](https://langchain-ai.github.io/langgraph/) and
[LangChain](https://www.langchain.com/). Supports OpenAI and Anthropic models, RAG via
ChromaDB, web search, Python code execution, and JSON-defined scenarios for repeatable
agent configurations.

## Features

- **Multiple agent types** — `assistant`, `web`, `research`, `code`, `rag`, `rewriter`,
  `evaluate`, `decomposer_tool`, and more
- **Multiple LLMs** — OpenAI (`oai`: gpt-4o, gpt-3.5-turbo) and Anthropic (`claude`:
  Opus, Sonnet, Haiku)
- **Optimization modes** — `cost`, `balanced`, `performance` to select the right model
  tier automatically (see [Model tiers](#model-tiers); `oai` has no `performance` model
  today)
- **Built-in tools** — attachable to the `assistant` agent via `-T`: `python` (REPL),
  `calculator`, `nerevutor`, `frobulator`. Web search (Bing) and Airtable are provided
  through dedicated agents/factories rather than `-T`.
- **Agent teams** — run supervised or unsupervised multi-agent groups on a task
- **Scenarios** — JSON-defined agent configs for repeatable, shareable workflows
- **RAG** — document retrieval via ChromaDB vector store
- **Evaluation** — run scenarios against every model and have an LLM judge each answer
  `yes` / `no` / `partially` (see [evaluate](#evaluate))

## Agent types

Passed to `-a/--agent` (repeatable) or a scenario's `agent_type`:

| Type | Description |
|------|-------------|
| `assistant` | General-purpose chat agent; the only type that accepts `-T` tools |
| `web` | Web-search assistant (Bing) |
| `research` | Researcher agent |
| `code` | Code-execution agent (Python via a user-proxy) |
| `rag` | Retrieval-augmented agent over local documents |
| `rag_alt` | Alternate RAG retriever (QA-style retrieval by default) |
| `rewriter` | Rewrites/refines queries or answers |
| `evaluate` | Scores responses (used by the `evaluate` command) |
| `decomposer_tool` | Task decomposition exposed as a tool |
| `decomposer_prompt` | Task decomposition via prompt |
| `decomposer_output` | Parses decomposition output |
| `calc_tool` | Calculator tool agent |
| `calc_tool_alt` | Alternate calculator tool agent |

## Model tiers

`-l/--llm` and `-o/--optimization` pick one model (`lib/models.py:88-137`):

| Optimization | OpenAI (`oai`) | Anthropic (`claude`) |
|---|---|---|
| `performance` | `gpt-4o` (intended; no model today) | `claude-3-opus-20240229` |
| `balanced` | `gpt-4o` | `claude-3-sonnet-20240229` |
| `cost` | `gpt-3.5-turbo` | `claude-3-haiku-20240307` |

`gpt-4o` is defined twice, and the `balanced` definition replaces the
`performance` one, so the model list has no `oai`/`performance` entry.
`-l oai -o performance` prints `No model found with optimization performance!`
(`langly.py:161-162`) and no chat runs.

## Setup

### [virtualenvwrapper](https://virtualenvwrapper.readthedocs.io/en/latest/)

```bash
mkvirtualenv --python=python3.11 langly
```

### venv

```bash
# ensure you have python v3.11
python3.11 -m venv .venv
. .venv/bin/activate
```

`pyproject.toml` requires Python 3.11.7 or later.

## Installation

```bash
pip install -r requirements.txt
pip install -e .
```

`pip install -e .` installs the `langly` command; its declared dependencies
are only `click`, so `requirements.txt` is what installs LangChain, LangGraph,
ChromaDB, and the rest.

Run `langly` from the project root: `scenarios.json`, `schemas/`, `resources/`,
and `chromadb/` are resolved against the current directory
(`lib/config.py:14-26`), and `schemas/oai/apis_guru.json` is opened at import
time.

## Configuration

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
BING_API_KEY=...          # required for web search
AIRTABLE_API_KEY=...      # required for Airtable tools
DOC_INTEL_API_KEY=...     # optional; Azure Document Intelligence
TEXTRACT_API_KEY=...      # optional; Amazon Textract
```

`OPENAI_API_KEY` is required even if you only use Claude: the OpenAI embedding
functions (`text-embedding-3-small`) are built at import time and used for all
RAG embeddings (`lib/config.py:63-71`). `DOC_INTEL_API_KEY` and
`TEXTRACT_API_KEY` are read by `lib/config.py:32-33` for document loaders.

## Usage

```text
langly [OPTIONS] COMMAND [ARGS]...
```

**Global options:** `--version`, `-v/--verbose` (repeatable, increases log verbosity),
`-q/--quiet` (errors only, overrides `-v`).

Unhandled exceptions open a post-mortem debugger (`langly.py:80`), and several
paths stop at a `breakpoint()` instead of exiting: an invalid scenario
`agent_type` (`langly.py:302`), a failed agent build (`langly.py:343`,
`langly.py:417`, `langly.py:714`), a chat with no model or agent
(`langly.py:473`, which is where every "not found" or "You must provide ..."
message in `chat` ends up), an `evaluate` run cap (`langly.py:412`), and a judge
answer other than `yes`/`no`/`partially` (`langly.py:778`). Don't run `langly`
unattended.

### chat

Interact with a single agent or a multi-agent team.

```bash
# Ask an assistant a question (OpenAI, balanced)
langly chat -a assistant -q "Summarize the history of the Roman Empire"

# Use Claude Haiku (cost-optimized) with streaming
langly chat -a assistant -l claude -o cost -s -q "Tell me a joke"

# Use a web-search agent
langly chat -a web -q "What happened in AI news this week?"

# Use a code-execution agent
langly chat -a code -q "Write and run a Python script that prints the Fibonacci sequence"

# Retrieval-augmented (RAG) agent over local documents
langly chat -a rag -q "What does the exchange-rate API return?"

# RAG over specific file types with a chosen search strategy and result count
# (-e and -n are accepted but have no effect today; see the option table)
langly chat -a rag -p ./resources -x pdf -x txt -e similarity -n 8 -Q -q "Summarize the onboarding docs"

# Equip the assistant with a calculator tool
langly chat -a assistant -T calculator -q "What is 44232 + 13312?"

# Run a multi-agent team (assistant + researcher), supervised
langly chat -a assistant -a research -q "Research and summarize recent advances in fusion energy"

# Run a multi-agent team, unsupervised (agents route themselves)
langly chat -a assistant -a research --unsupervised -q "Draft a report on quantum computing"

# Load a pre-defined scenario by index
langly chat -c 0

# Load a pre-defined scenario by ID (intended; no scenario has an id today)
langly chat -C my-scenario-id

# Verbose output
langly chat -a assistant -q "Explain LangGraph" -v
```

How `chat` picks what to run (`langly.py:628-741`):

1. `-a` given: the agents are built from the CLI options, and `-c`/`-C` are
   ignored. One `-a` builds that agent; several build a team. `-T` with
   several `-a` prints `Agent teams can't accepts tools!`; `-T` with a
   non-`assistant` agent prints `Only the assistant agent accepts tools!`.
2. `-c`/`-C` without `-a`: the scenario's `task` replaces `-q`, and its
   `agents` are built (per-agent `llm`/`optimization` override `-l`/`-o`).
   `-T` is ignored with `CLI tools ignored when loading agents from a scenario!`.
   A scenario with no `agents` prints `Library agent build is not yet
   implemented!` (or `Dynamic agent build is not yet implemented!` with
   `--no-use-agent-library`); building agents from the library is intended.
   The scenario's `supervisor_llm`/`supervisor_optimization` fill in whichever
   of `-L`/`-O` isn't given (`langly.py:650-652`).
3. Otherwise (including `-T` without `-a`) it prints `You must provide either
   agents or a scenario!`.

In every case where nothing was built, the chat then stops in the debugger
(`langly.py:473`).

**Key options:**

| Flag | Description |
|------|-------------|
| `-a, --agent` | Agent type (`assistant`, `web`, `research`, `code`, `rag`, `rewriter`, …). Repeatable for teams. |
| `-l, --llm` | LLM provider: `oai` (default) or `claude` |
| `-o, --optimization` | Model tier: `cost`, `balanced` (default), `performance` (not available for `oai`, see [Model tiers](#model-tiers)) |
| `-T, --tool` | Tool to attach to the `assistant` agent (`python`, `calculator`, `nerevutor`, `frobulator`). Repeatable. |
| `-L, --supervisor-llm` | LLM provider for the team supervisor (`oai`, `claude`). Takes effect only together with `-O` (`langly.py:185-190`). |
| `-O, --supervisor-optimization` | Model tier for the team supervisor (`cost`, `balanced`, `performance`). Takes effect only together with `-L`. |
| `-q, --query` | Task/question to send |
| `-c, --scenario` | Scenario index from `scenarios.json` (0-based) |
| `-C, --scenario-id` | Scenario ID from `scenarios.json` (intended; no scenario defines `id`, so this prints `Scenario ID ... not found!`) |
| `--scenarios-path` | Alternate scenarios file (default `scenarios.json`). Use the long form: `-P` is also declared for `--agent-library-path`, and click gives `-P` to that option. |
| `-s, --stream` | Stream the response |
| `-S, --supervised / --unsupervised` | Supervisor controls routing in multi-agent teams (default supervised). Use `--unsupervised`: `-u` is also declared for `--use-agent-library`, and click gives `-u` to that option, so `-u` never selects unsupervised. |
| `-A, --auto` | Enable automatic task optimization (picks the model tier per task from the scores in `resources/eval_results.csv`) |
| `-t, --temperature` | Sampling temperature, `0.0`–`1.0` (default `0.2`). `0.0` is treated as unset and the default `0.2` applies (`lib/funcs.py:555`). |
| `-b, --ability` | Override the agent's declared ability/instructions |
| `-p, --documents-path` | Directory of documents for the `rag` agent (default `resources/`) |
| `-x, --text-types` | Document types to ingest for RAG: `json`, `docx`, `pdf`, `txt`, `html`, `py`, `csv` (default `json`). Repeatable. |
| `-e, --search-type` | Vector search strategy: `mmr` (default) or `similarity`. Accepted but not passed to the retriever today, which always runs a similarity search (`lib/agents.py:176-178`, `lib/retriever.py:122-130`). `similarity_score_threshold` is not a choice. |
| `-Q, --qa` | Use question-and-answer style retrieval (`rag` only; `rag_alt` always uses it) |
| `-n, --result-count` | Max vector-store results to retrieve for RAG (default `8`). Accepted but not passed to the retriever today, which always retrieves 8 (`lib/agents.py:176-178`, `lib/retriever.py:236-249`). |
| `-E, --agent-executor / --no-agent-executor` | Wrap agents in a LangChain `AgentExecutor` |
| `-u, --use-agent-library / --no-use-agent-library` | Build agents from the generated agent library instead of on the fly (intended; neither path is implemented, see step 2 above) |
| `--agent-library-path` | Agent library file (default `resources/agent_library_example.json`); not used by `chat` today |
| `-v, --verbose` | Verbose output (a `chat` flag, separate from the global `-v`) |

### evaluate

Run scenarios and score each model's responses:

```bash
# Evaluate all scenarios
langly evaluate

# Evaluate specific scenarios by index
langly evaluate -c 0 -c 1 -c 2

# Evaluate with a specific judge LLM
langly evaluate -l claude -o cost
```

What a run does (`langly.py:346-417`, `langly.py:752-798`):

1. Builds the `evaluate` agent (the judge) with `-l`/`-o`. These options pick
   the judge, not the models under test.
2. For each selected scenario (all of them without `-c`), skips it with a
   message if it has no `agents` or no `task` (scenarios 40–43 have no
   agents).
3. Runs the scenario once against every model in the [model tier
   table](#model-tiers) (five models today), in random order. Each scenario
   agent's own `llm`/`optimization` is ignored here. A team is always
   supervised: `--unsupervised` is accepted but not passed on.
4. Sends each `[task, response]` pair to the judge, which must answer `yes`,
   `no`, or `partially`; the score is `1`, `0`, or `0.5`.
5. Appends the results to `resources/eval_results.csv` and rewrites the file.

Results are saved to `resources/eval_results.csv`. The file accumulates across
runs: it's loaded first, new rows are added, and the whole file is written back
(`lib/utils.py:459-494`). Columns:

| Column | Content |
|---|---|
| `key` | `<model name>:<agent id>:<hash of task>` |
| `node_name` | agent name, `<llm>_<optimization>_<name>` |
| `model_name` | model under test |
| `node_id` | agent id |
| `task` | scenario task |
| `response` | the agent's answer |
| `utcnow` | ISO 8601 UTC timestamp |
| `raw` | judge answer: `yes`, `no`, or `partially` |
| `score` | `1`, `0`, or `0.5` |

Each `key` is run at most 10 times (`max_runs=10`, `langly.py:354`). At the cap
the run logs `Skipping because run_count ... >= 10!` and then stops in the
debugger (`langly.py:408-412`) rather than skipping. The key uses Python's
`hash()` of the task, which changes between processes unless
`PYTHONHASHSEED` is fixed; with a random seed, rows from earlier runs never
count toward the cap or toward `-A` scores (`lib/runnable_funcs.py:475-488`).

### query-db

Query the ChromaDB vector store directly:

```bash
# Query the first collection, return 5 results
# (intended; crashes today without -c, so pass -c 0)
langly query-db "vector databases" -r 5

# Query a collection by index
langly query-db "vector databases" -c 2 -r 5

# Query a collection whose name contains "my_docs"
# (intended; rejected today, see -n below)
langly query-db "machine learning" --collection-name my_docs -r 10
```

**Options:**

| Flag | Description |
|------|-------------|
| `-c, --collection-num` | Collection index to query (used when no name is given). Has no default: without it the command raises `TypeError: list indices must be integers or slices, not NoneType` (`langly.py:815`); an index past the end raises `IndexError`. |
| `-n, --collection-name` | Match the first collection whose name contains this value (intended). Its default is the integer `0`, so click parses the value as an integer and rejects a name: `Invalid value for '-n' / '--collection-name': 'my_docs' is not a valid integer.` (`langly.py:804`) |
| `-r, --results` | Number of results to return (default `10`) |

Each line is `<rank>. [<distance>] <provider>:<service>:<document>`, with the
provider and service taken from the `info.x-providerName` and
`info.x-serviceName` metadata when present. The RAG agents store documents in
the `function-results` collection (and `function-results-questions` with QA
retrieval).

### gen-agent-lib

Generate a role-profile agent library used for dynamic agent building:

```bash
# Generate profiles for all built-in positions
langly gen-agent-lib

# Generate for specific positions
langly gen-agent-lib -s Programmer -s Data_Analyst
```

| Flag | Description |
|------|-------------|
| `-l, --llm` | LLM provider: `oai` (default) or `claude` |
| `-o, --optimization` | Model tier (default `balanced`) |
| `-t, --temperature` | Sampling temperature, `0.0`–`1.0` (default `0.2`) |
| `-p, --agent-library-path` | File to write, overwritten (default `resources/agent_library_example.json`) |
| `-s, --position` | Position to profile, repeatable. One of `Programmer`, `Astronomer`, `Data_Analyst`, `Journalist`, `Teacher`, `Lawyer`, `Mathematician`, `Physicist`, `Biologist`, `Chemist`, `Chief_Information_Security_Officer`, `Artificial_Intelligence_Engineer`, `Financial_Analyst` (default: all) |
| `-v, --verbose` | Verbose output |

The profiles are generated by the `code` agent (`langly.py:565`) and written
as a JSON list of `{"name": <position>, "profile": <answer>}`. `chat` doesn't
read the library yet.

### convert-schemas

Convert an OpenAPI schema to the OpenAI tool-call format:

```bash
langly convert-schemas my_api
# reads  schemas/openapi/my_api.json
# writes schemas/oai/my_api.json
```

The input must be OpenAPI 3.x JSON with a `servers` list; without one (for
example a Swagger 2.0 spec) the command logs `No servers found in OpenAPI
schema.` and exits with status 1 (`lib/utils.py:284-286`). Only the first
server URL is used. The output is meant for a scenario's `schemas` field,
which has no effect today (see below).

## Scenarios

Scenarios are JSON objects in `scenarios.json` that describe an agent configuration and
task:

```json
{
  "id": "calc-example",
  "task": "What is 44232 + 13312?",
  "agents": [
    {
      "agent_type": "assistant",
      "tools": ["calculator"],
      "llm": "claude",
      "optimization": "cost"
    }
  ],
  "eval_type": "fuzzy",
  "solutions": [57544]
}
```

Scenario 1 in `scenarios.json` is this example without the `id` (plus
`instructions` and `"agent_executor": false`).

Run it with:

```bash
langly chat -C calc-example   # intended; needs the "id" field, which no scenario has today
langly chat -c 1              # selects this scenario by index
langly evaluate -c 1
```

**Scenario fields:**

| Field | Description |
|-------|-------------|
| `id` | Identifier for `chat -C` (intended; no scenario defines one) |
| `task` | The prompt/task sent to the agent(s) |
| `agents` | List of agent configs (see below). Without it, `chat` prints that library agent build isn't implemented and `evaluate` skips the scenario. |
| `schemas` | Names of OpenAI tool schemas to attach as graph tools (intended; ignored today, the loader is commented out at `langly.py:435-442` and `langly.py:657-658`) |
| `eval_type` | How `evaluate` scores responses: `match`, `includes`, `fuzzy`, or `model` (LLM-judged) (intended; ignored today, every scenario is LLM-judged) |
| `solutions` | Accepted answer(s) for `match`/`includes`/`fuzzy` scoring (intended; ignored today) |
| `solutions_type` | Whether `any` or `all` solutions must match (default `any`) (intended; ignored today; scenario 37 also uses `count`) |
| `supervisor_llm` | LLM provider for the team supervisor |
| `supervisor_optimization` | Model tier for the team supervisor |

**Per-agent fields (`agents[]`):**

| Field | Description |
|-------|-------------|
| `agent_type` | Required. One of the agent types above |
| `id` / `name` | Optional identifier / display name |
| `instructions` | Custom system instructions |
| `ability` | Declared ability/role of the agent |
| `description` | Human-readable description |
| `temperature` | Per-agent sampling temperature |
| `llm` | `oai` or `claude` (ignored by `evaluate`) |
| `optimization` | `cost`, `balanced`, or `performance` (ignored by `evaluate`) |
| `auto` | Enable automatic per-task model selection |
| `tools` | Tool names (only for `assistant`; on any other type the agent isn't built) |
| `agent_executor` | Wrap the agent in a LangChain `AgentExecutor` |

With `eval_type: "model"`, the `evaluate` command uses the `evaluate` agent to judge
each response as `yes` / `no` / `partially`. That is how every scenario is judged today,
whatever its `eval_type`: `match`, `includes`, and `fuzzy` scoring against `solutions`
are intended (the fields are only declared in `lib/types.py:145-147`). Results are
written to `resources/eval_results.csv`.

## Known issues

- No `oai`/`performance` model: `gpt_4` is assigned twice (`lib/models.py:88-103`).
- `-u` on `chat` sets `--use-agent-library`, not `--unsupervised`, and `-P`
  sets `--agent-library-path`, not `--scenarios-path` (`langly.py:595-612`).
- `-e/--search-type` and `-n/--result-count` don't reach the retriever
  (`lib/agents.py:176-178`).
- `-t 0.0` is treated as unset (`lib/funcs.py:555`).
- `query-db` without `-c` raises `TypeError` (`langly.py:815`), and
  `--collection-name` only accepts integers (`langly.py:804`).
- `evaluate` can't save to the committed `resources/eval_results.csv`: that
  file's header has a `query` column, the code writes `task`, and
  `save_results` takes the header from the first loaded row, so `DictWriter`
  raises `ValueError: dict contains fields not in fieldnames: 'task'` after
  the file has been opened for writing (`lib/utils.py:459-473`). Move the old
  file aside before evaluating.
- `evaluate` stops in the debugger at the 10-run cap instead of skipping
  (`langly.py:408-412`), and ignores `--unsupervised` (`langly.py:766-767`).
- `eval_type`, `solutions`, `solutions_type`, and `schemas` are never read.
- `chat -C` can't match any scenario (`langly.py:642`).
- Agent-library builds are not implemented (`langly.py:722-725`).
- `web` and `research` agents use the Bing Search API, which Microsoft retired
  in August 2025.
