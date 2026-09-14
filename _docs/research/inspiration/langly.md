# langly

A CLI for running and evaluating multi-agent AI workflows built on [LangGraph](https://langchain-ai.github.io/langgraph/) and [LangChain](https://www.langchain.com/). Supports OpenAI and Anthropic models, RAG via ChromaDB, web search, Python code execution, and JSON-defined scenarios for repeatable agent configurations.

## Features

- **Multiple agent types** — `assistant`, `web`, `research`, `code`, `rag`, `rewriter`, `evaluate`, `decomposer_tool`, and more
- **Multiple LLMs** — OpenAI (`oai`: gpt-4o, gpt-3.5-turbo) and Anthropic (`claude`: Opus, Sonnet, Haiku)
- **Optimization modes** — `cost`, `balanced`, `performance` to select the right model tier automatically
- **Built-in tools** — attachable to the `assistant` agent via `-T`: `python` (REPL), `calculator`, `nerevutor`, `frobulator`. Web search (Bing) and Airtable are provided through dedicated agents/factories rather than `-T`.
- **Agent teams** — run supervised or unsupervised multi-agent groups on a task
- **Scenarios** — JSON-defined agent configs for repeatable, shareable workflows
- **RAG** — document retrieval via ChromaDB vector store

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

## Installation

```bash
pip install -r requirements.txt
pip install -e .
```

## Configuration

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
BING_API_KEY=...          # required for web search
AIRTABLE_API_KEY=...      # required for Airtable tools
```

## Usage

```
langly [OPTIONS] COMMAND [ARGS]...
```

**Global options:** `--version`, `-v/--verbose` (repeatable, increases log verbosity), `-q/--quiet` (errors only, overrides `-v`).

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
langly chat -a rag -p ./resources -x pdf -x txt -e similarity -n 8 -Q -q "Summarize the onboarding docs"

# Equip the assistant with a calculator tool
langly chat -a assistant -T calculator -q "What is 44232 + 13312?"

# Run a multi-agent team (assistant + researcher), supervised
langly chat -a assistant -a research -q "Research and summarize recent advances in fusion energy"

# Run a multi-agent team, unsupervised (agents route themselves)
langly chat -a assistant -a research --unsupervised -q "Draft a report on quantum computing"

# Load a pre-defined scenario by index
langly chat -c 0

# Load a pre-defined scenario by ID
langly chat -C my-scenario-id

# Verbose output
langly chat -a assistant -q "Explain LangGraph" -v
```

**Key options:**

| Flag | Description |
|------|-------------|
| `-a, --agent` | Agent type (`assistant`, `web`, `research`, `code`, `rag`, `rewriter`, …). Repeatable for teams. |
| `-l, --llm` | LLM provider: `oai` (default) or `claude` |
| `-o, --optimization` | Model tier: `cost`, `balanced` (default), `performance` |
| `-T, --tool` | Tool to attach to the `assistant` agent (`python`, `calculator`, `nerevutor`, `frobulator`). Repeatable. |
| `-L, --supervisor-llm` | LLM provider for the team supervisor (`oai`, `claude`) |
| `-O, --supervisor-optimization` | Model tier for the team supervisor (`cost`, `balanced`, `performance`) |
| `-q, --query` | Task/question to send |
| `-c, --scenario` | Scenario index from `scenarios.json` |
| `-C, --scenario-id` | Scenario ID from `scenarios.json` |
| `-s, --stream` | Stream the response |
| `-S/-u, --supervised/--unsupervised` | Supervisor controls routing in multi-agent teams |
| `-A, --auto` | Enable automatic task optimization (picks the model tier per task) |
| `-t, --temperature` | Sampling temperature, `0.0`–`1.0` |
| `-b, --ability` | Override the agent's declared ability/instructions |
| `-p, --documents-path` | Directory of documents for the `rag` agent (default `resources/`) |
| `-x, --text-types` | Document types to ingest for RAG: `json`, `docx`, `pdf`, `txt`, `html`, `py`, `csv` (default `json`). Repeatable. |
| `-e, --search-type` | Vector search strategy: `mmr` (default), `similarity`, `similarity_score_threshold` |
| `-Q, --qa` | Use question-and-answer style retrieval |
| `-n, --result-count` | Max vector-store results to retrieve for RAG |
| `-E, --agent-executor / --no-agent-executor` | Wrap agents in a LangChain `AgentExecutor` |
| `-u, --use-agent-library / --no-use-agent-library` | Build agents from the generated agent library instead of on the fly |

### evaluate

Run scenarios and score each model's responses:

```bash
# Evaluate all scenarios
langly evaluate

# Evaluate specific scenarios by index
langly evaluate -c 0 -c 1 -c 2

# Evaluate with a specific LLM
langly evaluate -l claude -o cost
```

Results are saved to `resources/eval_results.csv`.

### query-db

Query the ChromaDB vector store directly:

```bash
# Query the first collection, return 5 results
langly query-db "vector databases" -r 5

# Query a collection by index
langly query-db "vector databases" -c 2 -r 5

# Query a collection whose name contains "my_docs"
langly query-db "machine learning" --collection-name my_docs -r 10
```

**Options:**

| Flag | Description |
|------|-------------|
| `-c, --collection-num` | Collection index to query (used when no name is given) |
| `-n, --collection-name` | Match the first collection whose name contains this value |
| `-r, --results` | Number of results to return (default `10`) |

### gen-agent-lib

Generate a role-profile agent library used for dynamic agent building:

```bash
# Generate profiles for all built-in positions
langly gen-agent-lib

# Generate for specific positions
langly gen-agent-lib -s Programmer -s Data_Analyst
```

### convert-schemas

Convert an OpenAPI schema to the OpenAI tool-call format:

```bash
langly convert-schemas my_api
# reads  schemas/openapi/my_api.json
# writes schemas/oai/my_api.json
```

## Scenarios

Scenarios are JSON objects in `scenarios.json` that describe an agent configuration and task:

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

Run it with:

```bash
langly chat -C calc-example
langly evaluate -c 1
```

**Scenario fields:**

| Field | Description |
|-------|-------------|
| `task` | The prompt/task sent to the agent(s) |
| `agents` | List of agent configs (see below) |
| `schemas` | Names of OpenAI tool schemas to attach as graph tools |
| `eval_type` | How `evaluate` scores responses: `match`, `includes`, `fuzzy`, or `model` (LLM-judged) |
| `solutions` | Accepted answer(s) for `match`/`includes`/`fuzzy` scoring |
| `solutions_type` | Whether `any` or `all` solutions must match (default `any`) |
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
| `llm` | `oai` or `claude` |
| `optimization` | `cost`, `balanced`, or `performance` |
| `auto` | Enable automatic per-task model selection |
| `tools` | Tool names (only for `assistant`) |
| `agent_executor` | Wrap the agent in a LangChain `AgentExecutor` |

With `eval_type: "model"`, the `evaluate` command uses the `evaluate` agent to judge each response as `yes` / `no` / `partially`. Results are written to `resources/eval_results.csv`.
