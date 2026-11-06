---
source: ../../../../autogen/README.md
---

# cli_manager

A command-line harness for building and running
[Microsoft AutoGen](https://microsoft.github.io/autogen/) multi-agent group chats. It
wires together configurable agents (assistants, user proxies, and a Retrieval-Augmented
`RetrieveUserProxyAgent`), multiple LLM providers (OpenAI and Anthropic Claude), a
ChromaDB vector store, web tooling, and on-the-fly conversion of OpenAPI specs into
callable agent functions.

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
  ChromaDB vector store from the JSON files in `resources/`, supports MMR or
  similarity search, and offers an optional multi-vector "QA" mode that indexes
  generated hypothetical questions alongside source documents (see
  [Retrieval](#retrieval)).
- **OpenAPI → function tools** — convert an OpenAPI 3 spec into OpenAI
  function-call schemas and register them as agent-callable functions. Each
  generated function sends an HTTP `GET` to its path (see
  [Generated API functions](#generated-api-functions)). Agents can even
  discover, download, and define new API functions mid-conversation via the
  `apis_guru` catalog and the `define_functions` "inception" tool.
- **Built-in tools** — web search (Bing), web scraping + summarization, a
  calculator, and long-content summarization with map-reduce chunking. Web
  search and scraping don't work today (see [Known issues](#known-issues));
  summarization is used internally by the scraper and can't be registered as a
  tool on its own because it has no docstring (`lib/funcs.py:284`,
  `lib/funcs.py:166-173`).
- **Agent library autobuild** — generate a library of role-based agent profiles
  and let AutoGen's `AgentBuilder` assemble a team for an arbitrary task. Run
  `gen-agent-lib` first: the library file isn't shipped with the repo.

## Requirements

- Python 3.11+ (the code imports `enum.StrEnum` and `typing.NotRequired`, which
  are new in 3.11, and uses `match`). `pyproject.toml` still says `>=3.8`, but
  3.11 is the real floor.
- Dependencies in `requirements.txt` (AutoGen, LangChain, ChromaDB, Anthropic,
  OpenAI, Click, BeautifulSoup, etc.)
- An OpenAI API key, even when you only use Claude: retrieval embeddings
  (`text-embedding-3-small`), hypothetical-question generation, and
  `gen-agent-lib` always call OpenAI.

## Installation

```bash
pip install -r requirements.txt
# optional dev tooling (ruff)
pip install -r dev_requirements.txt
```

Create a `.env` file in the project root with the credentials you need:

```dotenv
OPENAI_API_KEY=sk-...
OPENAI_ORGANIZATION=org-...        # optional; not read by the code today
CLAUDE_API_KEY=sk-ant-...          # only needed for the claude provider
BING_API_KEY=...                   # only needed for the search_web tool
ANONYMIZED_TELEMETRY=False         # optional, quiets ChromaDB telemetry
```

`lib/config.py` reads only `OPENAI_API_KEY`, `CLAUDE_API_KEY`, and
`BING_API_KEY` (`lib/config.py:27-30`); `ANONYMIZED_TELEMETRY` is read by
ChromaDB itself. `OPENAI_ORGANIZATION` is accepted in the file but has no effect.

The `manage` script is the entry point. Run it directly (`./manage ...`) from
the project root: every path (`scenarios.json`, `schemas/`, `resources/`,
`chromadb/`, `groupchat/`) is resolved against the current directory
(`lib/config.py:12-24`), and `schemas/oai/apis_guru.json` is opened at import
time, so running from anywhere else fails before any command starts.

Running it after installing the package, via the `manage` console script
defined in `pyproject.toml`, is intended but doesn't work today: there is no
`[build-system]` table, so the build falls back to setuptools, which stops with
"Multiple top-level packages discovered in a flat-layout: ['lib', 'schemas',
'resources']". The `[tool.flit.module]` entry also names a `manage` module,
but the script has no `.py` extension, and `dependencies` lists only `click`.

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
# (intended; rejected today, see the --agent row below)
./manage build-agents --task "What is 44232 + 13312?" \
  --agent user_proxy --agent assistant

# Autobuild a team from the agent library for an open-ended task
# (run ./manage gen-agent-lib first)
./manage build-agents --task "Find recent papers on explainable AI" \
  --use-agent-library
```

How the roster is chosen:

1. With `--scenario N`, the scenario's `task` replaces `--task` and its
   `agents` replace any `--agent` values. An index past the end prints
   `Scenario N not found!` and the command carries on with the CLI values.
2. With a task and at least one agent, the agents are built and the chat starts
   (see [Who drives the chat](#who-drives-the-chat)).
3. With a task and no agents (no `--agent`, or a scenario without `agents`,
   such as scenarios 13–16), the team is autobuilt from the agent library with
   AutoGen's `AgentBuilder.build_from_library`, using the selected model as both
   builder and agent model. This needs the library file from `gen-agent-lib`
   (`resources/agent_library_example.json` by default). With
   `--no-use-agent-library` it prints `Dynamic agent build is not yet
   implemented!` instead.
4. With no task it prints `You must provide a task!`.

Key options:

| Option | Values / Default | Purpose |
| --- | --- | --- |
| `-l, --llm` | `oai` (default), `claude` | LLM provider |
| `-o, --optimization` | `performance`, `balanced` (default), `cost` | Model tier |
| `--task` | text | Task prompt (overridden by a scenario's own task) |
| `-P, --agent` | `conversable`, `assistant`, `user_proxy`, `retriever` (repeatable) | Ad-hoc agent roster (intended). Today the choice list is empty, so click rejects every value: `AGENT_TYPES` tests `isinstance(<return annotation>, ConversableAgent)`, and the annotation is a class, never an instance (`manage:111-126`) |
| `--search-type` | `mmr` (default), `similarity` | Retriever search strategy |
| `-s, --scenario` | int | Index into `scenarios.json` |
| `--scenarios-path` | path (default `scenarios.json`) | Alternate scenarios file |
| `-S, --similarity` | flag | Use embedding similarity (`all-mpnet-base-v2`) when building from the agent library |
| `-q, --qa` | flag | Enable multi-vector QA retrieval (hypothetical questions). Not forwarded to the retriever today, so QA retrieval stays off (`manage:507-512`, `manage:229`) |
| `--temperature` | 0.0–1.0 (default 0.2) | Sampling temperature; a scenario agent's own `temperature` wins |
| `-u/--use-agent-library / --no-use-agent-library` | default on | Use the prebuilt agent library vs. dynamic build (dynamic build is not implemented) |
| `--agent-library-path` | path (default `resources/agent_library_example.json`) | Alternate agent library file |
| `-U, --use-oai-assistant` | flag | Use the OpenAI Assistants API (intended; accepted but has no effect today, and the `gpt_assistant` builder is a stub, `lib/agents.py:467`) |

> Note: several short flags collide (`-t` and `-p` are reused across options).
> `-t` is declared for `--task`, `--search-type`, and `--temperature`, and `-p`
> for `--scenarios-path` and `--agent-library-path` (`manage:433-459`).
> Prefer the long-form options shown above to avoid ambiguity.

### `convert-schemas NAME` — OpenAPI → OpenAI function schemas

Reads `schemas/openapi/<NAME>.json` and writes OpenAI function-call schemas to
`schemas/oai/<NAME>.json`, overwriting any existing file.

```bash
./manage convert-schemas exchangerate_api
```

The input must be an OpenAPI 3.x JSON document with a `servers` list. A spec
without `servers` (for example a Swagger 2.0 spec, which uses
`host`/`basePath`) logs `No servers found in OpenAPI schema.` and exits with
status 1 (`lib/utils.py:271-273`). Only the first server URL is used
(`lib/utils.py:275`).

Each operation becomes one schema entry:

| Key | Derived from |
| --- | --- |
| `name` | `<provider>_<operation>`: provider is `info.x-providerName`, else `info.title`, else the server host, lowercased with `.`, `-`, and spaces turned into `_`; operation is the `operationId` in snake_case, else `<method>_<path>` |
| `description` | the operation's `description`, else its `summary` |
| `path` | `<server URL>/<path>` with each `{param}` replaced by a positional `{0}`, `{1}`, … |
| `parameters` | an object schema with one property per declared parameter (its `schema.type`, plus `description` and any `example`), and `required` names; `$ref` parameters are resolved from `components.parameters` |

The HTTP method and any `requestBody` are not kept (`lib/utils.py:287-336`).

### `gen-agent-lib` — generate an agent library

Uses an LLM to produce role/profile system messages for a set of positions and
writes them to the agent library file.

```bash
./manage gen-agent-lib --optimization balanced
./manage gen-agent-lib --position Programmer --position Data_Analyst
```

| Option | Values / Default | Purpose |
| --- | --- | --- |
| `-o, --optimization` | `performance`, `balanced` (default), `cost` | Model tier. The model is always the OpenAI one for that tier, whatever provider you use elsewhere (`manage:401`) |
| `-p, --agent-library-path` | path (default `resources/agent_library_example.json`) | File to write (overwritten) |
| `-P, --position` | text, repeatable | Positions to profile. Default: `Programmer`, `Astronomer`, `Data_Analyst`, `Journalist`, `Teacher`, `Lawyer`, `Mathematician`, `Physicist`, `Biologist`, `Chemist`, `Chief_Information_Security_Officer`, `Artificial_Intelligence_Engineer`, `Financial_Analyst` |

The file is a JSON list of `{"name": <position>, "profile": <one-sentence
"As a ..." requirement>}`.

### `query-db QUERY` — search the vector store

Queries the ChromaDB store built under `chromadb/` and prints ranked results
with distances.

```bash
./manage query-db "currency exchange rate api" --results 5
```

`-n, --results` sets the number of results (default 10). The command queries
only the first collection ChromaDB lists (`manage:561-562`), and each line is
`<rank>. [<distance>] <provider>:<service>:<document>`, with the provider and
service read from the `info.x-providerName` and `info.x-serviceName` metadata
keys. Those keys exist only on documents indexed from the APIs.guru listing
(`resources/api_apis_guru_v2_list_lite.json`, see
`schemas/schema_parsers.json`); any other document raises `KeyError`
(`manage:572`). After a retriever has run there are two collections
(`text-embedding-3-small-function-results` and its `-questions` companion), and
which one is first isn't fixed.

## Scenario schema

`scenarios.json` is a list of scenarios. Each scenario has an optional `task`
string and an optional list of `agents`; a scenario without `agents` is
autobuilt from the agent library (see `build-agents`).

```jsonc
{
  "task": "Get the EUR exchange rate vs USD and GBP.",
  "agents": [
    {
      "agent_type": "user_proxy",          // conversable | assistant | user_proxy | retriever
      "name": "Director",                  // optional; agents are named <llm>_<optimization>_<name>
      "instructions": "You are ...",        // optional system message
      "description": "...",                 // optional group-chat description (intended; ignored today)
      "human_input_mode": "NEVER",          // ALWAYS | TERMINATE | NEVER (user_proxy only)
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
  - `gpt_assistant` is also accepted, but its builder is a stub
    (`lib/agents.py:467`) and fails.
- **`name`** — defaults to the builder's name (`ConversableAgent`, `Assistant`,
  `UserProxy`, `Retriever`). Other fields refer to agents by this name: the
  reference is compared, case-insensitively and with underscores removed, to
  the last `_`-separated part of the full `<llm>_<optimization>_<name>`
  (`manage:206-211`). So a name that itself contains `_` can't be referenced,
  and a reference that matches no agent stops in the debugger
  (`manage:215-217`).
- **`instructions`** — the system message; every agent's message gets a fixed
  epilogue offering a "$500 tip" and asking for `TERMINATE` when done
  (`lib/config.py:47-48`).
- **`description`** — accepted but not passed to any agent builder today.
- **`human_input_mode`** — used by `user_proxy` agents only (default `NEVER`);
  retrievers are always `NEVER`.
- **`funcs`** — register a function defined in `lib/funcs.py` (e.g. `scrape_web`,
  `search_web`, `calculator`). `caller` names the agent allowed to invoke it;
  the enclosing agent executes it. Without `caller`, the enclosing agent calls
  it too. Only functions with a docstring are registered (`search_web`,
  `scrape_web`, `calculator`); others log `Function ... has no docstring! Not
  registering.` (`lib/funcs.py:166-173`).
- **`schemas`** — load `schemas/oai/<name>.json` and register each entry as a
  callable HTTP function, executed by the enclosing agent and called by
  `caller` (see [Generated API functions](#generated-api-functions)).
- **`retrievers`** — only meaningful on a `retriever` agent; wires the
  `retrieve_content` tool so `executor` can run it on behalf of `caller`.
- **`define`** — attaches the `define_functions` tool, letting the named agent
  add new API functions to the conversation from a downloaded OpenAPI spec.
  The functions it defines are registered on that agent, which both calls and
  executes them (`lib/funcs.py:207-208`).

### Who drives the chat

`get_group_chat_manager` (`lib/agents.py:555-623`) picks the driver and the
chat shape:

1. If any agent has the `retrieve_content` tool (from `retrievers`), every
   `RetrieveUserProxyAgent` is removed from the chat; it still answers through
   the tool. More than one agent with `retrieve_content` logs a warning.
2. The driver is the first `RetrieveUserProxyAgent` still in the chat, wherever
   it sits in the list; only if there is none is it the first `UserProxyAgent`.
   Agent order matters only among agents of the same kind.
3. With three or more agents left, a `GroupChat` (at most 16 rounds, introductions
   on, no speaker twice in a row) is run by a `GroupChatManager`, and the
   driver opens the chat with the task.
4. With exactly two agents left, no `GroupChat` is built: the driver chats
   with the other agent directly.
5. With one agent left, or with no user proxy or retriever, no chat is
   started. If the scenario listed exactly two agents and the second is the
   retriever, the run logs "With only two agents, either set user_proxy to the
   RetrieveUserProxyAgent, or ensure the RetrieveUserProxyAgent is listed
   first in the schema." and does nothing (`lib/agents.py:658-662`); this is
   the one case where listing the retriever first matters. Otherwise the first
   agent generates a single reply to the task and the result is logged.

Every agent uses `max_tokens=512` and a 60-second timeout
(`lib/config.py:38-39`, `lib/agents.py:406-417`); user proxies auto-reply at
most 8 times in a row and retrievers once.

### Generated API functions

Each `schemas` entry (and each function added by `define_functions`) becomes a
Python function that (`lib/funcs.py:40-144`):

- always sends `GET`, whatever the operation's method, with no request body,
  headers, or authentication;
- fills the path's `{0}`, `{1}`, … placeholders positionally, in the order the
  parameters are declared, and drops a `/None` segment for an omitted optional
  value. Parameters that aren't in the path (query parameters) are not sent;
- accepts only `string` and `object` parameter types. Any other type
  (`integer`, `number`, `boolean`, `array`) raises `KeyError` while the
  function is built (`lib/funcs.py:35`, `lib/funcs.py:137`).

What it returns depends on the response:

| Case | Result |
| --- | --- |
| A file for this URL already exists in `schemas/openapi/` | a message pointing to `define_functions`; no request is sent |
| `2xx`, URL ends in `swagger.json` or `openapi.json` | the spec is saved to `schemas/openapi/<host>_<path>.json` and a message points to `define_functions` |
| `2xx`, response estimated at more than 512 tokens, retriever present | the JSON is saved to `resources/<host>_<path>.json`, added to the vector DB, and a message says to use `retrieve_content` |
| `2xx`, more than 512 tokens, no retriever | an error message; the data is dropped |
| `2xx`, otherwise | the response JSON |
| non-`2xx` | `{"message": <reason>, "suggestion": ...}` |

The first case applies to the shipped `apis_guru` catalog function: its URL
(`https://api.apis.guru/v2/list.json`) maps to
`schemas/openapi/api_apis_guru_v2_list.json`, which is committed, so it never
calls APIs.guru and always answers with the `define_functions` message.

The token estimate is the pickled response size divided by 5
(`lib/funcs.py:85`). Files written to `schemas/openapi/` and `resources/` stay in
the repo after the run.

### Retrieval

A `retriever` agent indexes on startup (`lib/agents.py:503-552`,
`lib/agents.py:317-336`):

- Only `*.json` files in `resources/` are indexed (`custom_text_types:
  ["json"]`); other files there are ignored.
- Documents go into the persistent ChromaDB collection
  `text-embedding-3-small-function-results` under `chromadb/`, and documents
  already present (by SHA-256 of their content) are skipped. Embeddings always
  use OpenAI `text-embedding-3-small`, whatever `--llm` is.
- For every new batch, three hypothetical questions per document are generated
  with OpenAI `gpt-4-turbo-preview` and stored in the
  `...-function-results-questions` collection, whether or not QA retrieval is
  on (`lib/agents.py:235`). Indexing a large file costs one LLM call per
  document.
- JSON files are split with a jq schema from `schemas/schema_parsers.json`
  (keyed by file name), else one inferred via GenSON.
- Retrieval returns up to 8 results using `--search-type` (MMR by default). QA
  retrieval (searching the generated questions) would be selected by `--qa`,
  but that flag doesn't reach the retriever today.

## Model / optimization matrix

| Optimization | OpenAI (`oai`) | Anthropic (`claude`) |
| --- | --- | --- |
| `performance` | `gpt-4` | `claude-3-opus-20240229` |
| `balanced` | `gpt-4-turbo-preview` | `claude-3-sonnet-20240229` |
| `cost` | `gpt-3.5-turbo` | `claude-3-haiku-20240307` |

## Project layout

```text
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
- The retriever indexes the JSON files in `resources/` on startup and infers a
  jq schema (via GenSON) for each unless an entry exists in
  `schemas/schema_parsers.json`.
- `sys.excepthook` drops into a post-mortem debugger (`ipdb`/`pdb`) on unhandled
  exceptions; several code paths also call `breakpoint()` for unimplemented cases
  (an unknown agent reference, `manage:217`; a failed model-client registration,
  `lib/agents.py:401`). Don't run it unattended.

## Known issues

- `--agent` accepts no values: `AGENT_TYPES` is always empty (`manage:111-126`).
- `--qa` is never passed to the retriever (`manage:507-513`).
- `--use-oai-assistant` has no effect (`manage:460`, `manage:474`).
- A scenario agent's `description` is ignored (`lib/agents.py:420-552`).
- `scrape_web` passes its arguments to `summarize` in the wrong order
  (`lib/funcs.py:376` against `lib/funcs.py:284`), so it returns the objective
  text instead of a summary of the page.
- `search_web` sends its query as a JSON body on a `GET` request
  (`lib/funcs.py:263-269`), and Microsoft retired the Bing Search APIs in
  August 2025, so it returns an empty result list.
- Generated API functions raise `KeyError` for any parameter type other than
  `string` or `object` (`lib/funcs.py:35`, `lib/funcs.py:137`), always send
  `GET`, and never send query parameters (`lib/funcs.py:56-71`).
- `convert-schemas` exits on a Swagger 2.0 spec (`lib/utils.py:271-273`).
- `query-db` raises `KeyError` on any document without
  `info.x-providerName` metadata (`manage:572`).
- The `manage` console script can't be installed (`pyproject.toml`).

## License

See [LICENSE](LICENSE).
