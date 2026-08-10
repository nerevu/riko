# cli_manager

A command-line harness for building and running [Microsoft AutoGen](https://microsoft.github.io/autogen/)
multi-agent group chats. It wires together configurable agents (assistants, user
proxies, and a Retrieval-Augmented `RetrieveUserProxyAgent`), multiple LLM
providers (OpenAI and Anthropic Claude), a ChromaDB vector store, web tooling,
and on-the-fly conversion of OpenAPI specs into callable agent functions.

Agents and tasks are described declaratively in `scenarios.json`, so a full
multi-agent workflow can be launched from a single command without writing code.

## Features

- **Declarative agent scenarios** — describe a task and a roster of agents (with
  instructions, tools, retrievers, and per-agent LLM/optimization overrides) in
  `scenarios.json` and run them by index.
- **Multi-provider LLMs** — OpenAI (`gpt-4`, `gpt-4-turbo-preview`,
  `gpt-3.5-turbo`) and Claude (`opus`, `sonnet`, `haiku`) via a custom AutoGen
  `AnthropicClient`. Model selection is driven by an `optimization` tier rather
  than a hard-coded model name.
- **Optimization tiers** — `performance`, `balanced`, and `cost` map to the
  appropriate model for the chosen provider (see the table below).
- **Retrieval-Augmented Generation** — `MyRetrieveUserProxyAgent` builds a
  ChromaDB vector store from files in `resources/`, supports MMR or similarity
  search, and offers an optional multi-vector "QA" mode that indexes generated
  hypothetical questions alongside source documents.
- **OpenAPI → function tools** — convert an OpenAPI/Swagger spec into OpenAI
  function-call schemas and register them as agent-callable functions. Agents
  can even discover, download, and define new API functions mid-conversation
  via the `apis_guru` catalog and the `define_functions` "inception" tool.
- **Built-in tools** — web search (Bing), web scraping + summarization, a
  calculator, and long-content summarization with map-reduce chunking.
- **Agent library autobuild** — generate a library of role-based agent profiles
  and let AutoGen's `AgentBuilder` assemble a team for an arbitrary task.

## Requirements

- Python 3.8+ (the code uses 3.11+ syntax such as `match`/`StrEnum`, so 3.11+ is
  recommended)
- Dependencies in `requirements.txt` (AutoGen, LangChain, ChromaDB, Anthropic,
  OpenAI, Click, BeautifulSoup, etc.)

## Installation

```bash
pip install -r requirements.txt
# optional dev tooling (ruff)
pip install -r dev_requirements.txt
```

Create a `.env` file in the project root with the credentials you need:

```dotenv
OPENAI_API_KEY=sk-...
OPENAI_ORGANIZATION=org-...        # optional
CLAUDE_API_KEY=sk-ant-...          # only needed for the claude provider
BING_API_KEY=...                   # only needed for the search_web tool
ANONYMIZED_TELEMETRY=False         # optional, quiets ChromaDB telemetry
```

The `manage` script is the entry point. Run it directly (`./manage ...`) or,
after installing the package, via the `manage` console script defined in
`pyproject.toml`.

## Usage

Global options apply to every command:

- `-v, --verbose` — increase logging verbosity (repeatable)
- `-q, --quiet` — log errors only (overrides `-v`)

### `build-agents` — run a multi-agent chat

The primary command. Either run a predefined scenario by index or assemble
agents ad hoc from the CLI.

```bash
# Run scenario 2 from scenarios.json (a calculator task)
./manage build-agents --scenario 2

# Run scenario 12 (multi-API research team) using Claude, cost-optimized
./manage build-agents --scenario 12 --llm claude --optimization cost

# Ad-hoc: a user proxy + assistant for a one-off task
./manage build-agents --task "What is 44232 + 13312?" \
  --agent user_proxy --agent assistant

# Autobuild a team from the agent library for an open-ended task
./manage build-agents --task "Find recent papers on explainable AI" \
  --use-agent-library
```

Key options:

| Option | Values / Default | Purpose |
| --- | --- | --- |
| `-l, --llm` | `oai` (default), `claude` | LLM provider |
| `-o, --optimization` | `performance`, `balanced` (default), `cost` | Model tier |
| `--task` | text | Task prompt (overridden by a scenario's own task) |
| `-P, --agent` | `conversable`, `assistant`, `user_proxy`, `retriever` (repeatable) | Ad-hoc agent roster |
| `--search-type` | `mmr` (default), `similarity` | Retriever search strategy |
| `-s, --scenario` | int | Index into `scenarios.json` |
| `--scenarios-path` | path | Alternate scenarios file |
| `-S, --similarity` | flag | Use embedding similarity when building the agent library |
| `-q, --qa` | flag | Enable multi-vector QA retrieval (hypothetical questions) |
| `--temperature` | 0.0–1.0 (default 0.2) | Sampling temperature |
| `-u/--use-agent-library / --no-use-agent-library` | default on | Use the prebuilt agent library vs. dynamic build |
| `--agent-library-path` | path | Alternate agent library file |
| `-U, --use-oai-assistant` | flag | Use the OpenAI Assistants API |

> Note: several short flags collide (`-t` and `-p` are reused across options).
> Prefer the long-form options shown above to avoid ambiguity.

### `convert-schemas NAME` — OpenAPI → OpenAI function schemas

Reads `schemas/openapi/<NAME>.json` and writes OpenAI function-call schemas to
`schemas/oai/<NAME>.json`.

```bash
./manage convert-schemas exchangerate_api
```

### `gen-agent-lib` — generate an agent library

Uses an LLM to produce role/profile system messages for a set of positions and
writes them to the agent library file.

```bash
./manage gen-agent-lib --optimization balanced
./manage gen-agent-lib --position Programmer --position Data_Analyst
```

### `query-db QUERY` — search the vector store

Queries the ChromaDB store built under `chromadb/` and prints ranked results
with distances.

```bash
./manage query-db "currency exchange rate api" --results 5
```

## Scenario schema

`scenarios.json` is a list of scenarios. Each scenario has an optional `task`
string and a list of `agents`. The order of agents matters — the group-chat
manager treats the first `UserProxyAgent`/`RetrieveUserProxyAgent` as the driver.

```jsonc
{
  "task": "Get the EUR exchange rate vs USD and GBP.",
  "agents": [
    {
      "agent_type": "user_proxy",          // conversable | assistant | user_proxy | retriever
      "name": "Director",                  // optional; agents are named <llm>_<optimization>_<name>
      "instructions": "You are ...",        // optional system message
      "description": "...",                 // optional group-chat description
      "human_input_mode": "NEVER",          // ALWAYS | TERMINATE | NEVER
      "temperature": 0.0,                    // optional per-agent override
      "optimization": "performance",         // optional per-agent override
      "llm": "claude",                       // optional per-agent provider override

      // Register a Python function from lib/funcs.py as a tool, called by another agent
      "funcs": [{ "name": "scrape_web", "caller": "Researcher" }],

      // Register functions generated from an OpenAPI spec in schemas/oai/<name>.json
      "schemas": [{ "name": "apis_guru", "caller": "director" }],

      // For retriever agents: expose retrieve_content to other agents
      "retrievers": [{ "executor": "director", "caller": "manager" }],

      // Give an agent the define_functions "inception" tool
      "define": "director"
    }
  ]
}
```

Field reference:

- **`agent_type`** — one of the builders in `lib/agents.py`:
  - `conversable` — a generic `ConversableAgent`
  - `assistant` — an `AssistantAgent` (writes/debugs Python)
  - `user_proxy` — a `UserProxyAgent` that executes code (in `groupchat/`) and
    relays feedback
  - `retriever` — the RAG `MyRetrieveUserProxyAgent`
- **`funcs`** — register a function defined in `lib/funcs.py` (e.g. `scrape_web`,
  `search_web`, `calculator`). `caller` names the agent allowed to invoke it;
  the enclosing agent executes it.
- **`schemas`** — load `schemas/oai/<name>.json` and register each entry as a
  callable HTTP function.
- **`retrievers`** — only meaningful on a `retriever` agent; wires the
  `retrieve_content` tool so `executor` can run it on behalf of `caller`.
- **`define`** — attaches the `define_functions` tool, letting the named agent
  add new API functions to the conversation from a downloaded OpenAPI spec.

## Model / optimization matrix

| Optimization | OpenAI (`oai`) | Anthropic (`claude`) |
| --- | --- | --- |
| `performance` | `gpt-4` | `claude-3-opus-20240229` |
| `balanced` | `gpt-4-turbo-preview` | `claude-3-sonnet-20240229` |
| `cost` | `gpt-3.5-turbo` | `claude-3-haiku-20240307` |

## Project layout

```
manage                 CLI entry point (Click command group)
scenarios.json         Predefined agent/task scenarios
lib/
  agents.py            Agent builders, group-chat manager, RAG retriever
  clients.py           AnthropicClient adapter for AutoGen + cost accounting
  config.py            Paths, constants, keys, embedding function
  funcs.py             Agent tools + OpenAPI→function generation
  models.py            LLM/Model definitions, optimization tiers, configs
  utils.py             Schema inference, OpenAPI conversion, logging helpers
schemas/
  openapi/             Source OpenAPI/Swagger specs
  oai/                 Converted OpenAI function-call schemas
  schema_parsers.json  jq parsing hints for JSON documents added to the vector db
resources/             Documents indexed by the retriever + agent library
examples/              Standalone example scripts and notebooks
```

## Notes

- Code execution by `UserProxyAgent` runs in the `groupchat/` working directory
  with Docker disabled (`use_docker=False`).
- The retriever indexes files from `resources/` on startup and, for JSON files,
  infers a jq schema (via GenSON) unless an entry exists in
  `schemas/schema_parsers.json`.
- `sys.excepthook` drops into a post-mortem debugger (`ipdb`/`pdb`) on unhandled
  exceptions; several code paths also call `breakpoint()` for unimplemented cases.

## License

See [LICENSE](LICENSE).
