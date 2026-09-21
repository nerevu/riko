# Welcome to Nerevu

## How We Use Claude

Claude Code is the day-to-day pair on `riko`, a Python stream-processing engine
modeled after Yahoo! Pipes. Most sessions are one of: fixing a bug, writing or
syncing docs, tightening types/tests, or building a feature slice on the
experimental `next` branch. Sessions are short and single-purpose: one task, gate it, commit, wrap up,
`/clear`.

The one rule that shapes everything else: **the human commits, Claude never does.**
Skills prepare the tree and suggest a commit message; you run `git commit`.

## Your Setup Checklist

### Codebases
- [ ] riko — https://github.com/nerevu/riko (primary). Three branches matter: `main` is the released code, `features` is where release-bound work lands and the changelog is curated, and `next` is the experimental branch where in-flight work lives without clogging the changelog. Most Claude sessions run on `next`.
- [ ] meza — https://github.com/reubano/meza (pinned by `pyproject.toml`; owns low-level data conversion)
- [ ] mezmorize — https://github.com/reubano/mezmorize (memoizes the URL opener in `riko/io/_sync.py`)
- [ ] riko-tutorial — https://github.com/reubano/riko-tutorial (worked examples)

### MCP Servers to Activate
- [ ] serena — semantic code navigation (symbol search, references, overviews). The most-used tool by far. Add https://github.com/oraios/serena to your MCP config and run its `initial_instructions` once per session. Use it for *navigation*; its `replace_symbol_body` has corrupted code before, so let Claude edit with the built-in Edit tool.
- [ ] sequential-thinking — structured multi-step reasoning for design/debug knots. https://github.com/modelcontextprotocol/servers
- [ ] context7 — current library docs on demand (anyio, httpx, attrs, click…). https://context7.com

### Skills to Know About

Repo-shipped skills live in `.claude/skills/` and come with the clone:

- [ ] /riko — codebase expert mode; loads the architecture/API/typing context for `next`. Invoke at the start of any non-trivial session.
- [ ] /land — runs the full pre-commit gate (prettify, codegen drift, `lint --all`, tests, type check) and reports ready/not-ready with a suggested commit message. Never commits.
- [ ] /triage — decides who owns a defect *before* fixing it: local fix (regression test + CHANGES line) or a strict-xfail tripwire for the gameplan phase that owns it.
- [ ] /wrapup — syncs `_docs/IMPLEMENTED.md`, `PHASE_CHECKLISTS.md`, the owning gameplan, `docs/CHANGES.rst`, and Claude memory so you can `/clear` without losing state.

User-level skills (copy from a teammate's `~/.claude/skills/` and `~/.claude/commands/`):

- [ ] /go — implement a feature end-to-end against project conventions and gates. The workhorse.
- [ ] /architect — for multi-component or design-sensitive work: plan first, delegate build, verify.
- [ ] /diagnose — root-cause a bug with evidence, fix the cause, lock it with a regression test.
- [ ] /audit — read-only defect sweep (whole repo, since a commit, or the working tree). Feed its findings to /triage.
- [ ] /claude-api — Claude API / SDK reference (model ids, params, tool use, caching).

### The change lifecycle

```
/riko  →  /go (or /diagnose, /architect)  →  /land  →  you commit  →  /wrapup  →  /clear
```

Findings from `/audit` go through `/triage` before anyone fixes them.

## Team Tips

**Environment**
- Python 3.12+ and `uv`. Install with `uv sync --group dev --all-extras`. Add `--active` to `uv sync` / `uv run` only when your shell venv should win over the project's `.venv`.
- `manage` (`riko.cli.manage:manager`) is the task runner. If the wrong `manage` executable wins (mezmorize ships one too), use `python -m riko.cli.manage ...`.
- Full gate, in order: `manage prettify` → `manage codegen --all` → `manage lint --all` → `manage test --no-cov` → `manage lint --check-types`. `lint --all` already covers Ruff, RST, docs freshness, docstrings, and every import contract, so do not rerun those pieces separately. Always prettify before linting; never hand-fix formatting-class lint errors.
- Doctests are tests: `pytest` collects `riko/`, `tests/`, `examples/`, `README.rst`, and `docs/`. Run one file with `uv run manage test --no-cov --where <path>`.

**Where the truth lives**
- `CLAUDE.md` is the router: package layers, API tiers, cross-cutting invariants, style, quirks. Read it before touching code.
- `_docs/PHASE_CHECKLISTS.md` is the live status; `_docs/gameplans/` own the *target* behavior for each concept. If a defect's correct fix belongs to a planned phase, leave a tripwire rather than an interim fix (that is what `/triage` decides).
- Generated files are never hand-edited: `riko/coercion/_configs.py`, `riko/modules/_names.py`, `riko/types/_module_ids.py`, and the marked blocks in `_docs/API_SURFACE.md`. Regenerate with `manage codegen`.
- Claude's project memory lives in `~/.claude/projects/-…-riko/memory/`. `/wrapup` maintains it; `session-handoff.md` there is the pickup point for the next session.

**Rules that bite newcomers**
- Architecture is enforced: `base < types < {bado|coercion|definitions} < io < parsing < rss`, execution and runtime above, then `modules`/`ext`, `api`, `cli`. Never import upward; `manage lint imports --architecture` will fail the gate.
- `is None`, never truthiness: `0`, `False`, and `""` are valid values.
- One `return` per function; no early returns.
- No internal jargon in shipped text: phase codes, gameplan refs, `_docs/` paths, and ticket ids never appear in docstrings, comments, test names, `docs/*.rst`, or runtime messages.
- Docstrings say what the caller gets, not how it works; summaries start with an action verb, never "Returns"/"Yields". Standard: `_docs/DOCUMENTATION_STANDARD.md`.
- Bug fixes are a regression test plus one `docs/CHANGES.rst` line, never prose in `CLAUDE.md` or `_docs/`.
- Internal modules import from a symbol's defining module, never `from riko import …`; only user-facing docs show the facade.
- Commit subjects carry a tag: `[NEW]`, `[ENH]`, `[FIX]`, `[CHANGE]`, `[REFACTOR]`, `[TEST]`, `[DOCS]`, `[DEV]`. Use `fixup!` commits freely on `next`; they get squashed before work moves to `features`.
- `_docs/` holds internal Markdown (plans, status, this guide). The repo root and `docs/` hold the external RST that ships to users. Do not mix the two.

## Get Started

1. Clone `riko`, check out `next`, and run `uv sync --group dev --all-extras`.
2. Read `CLAUDE.md`, then skim `_docs/PHASE_CHECKLISTS.md` for the current status.
3. Confirm the setup: `uv run manage test --no-cov` and `uv run manage lint --all`.
4. Start a session with `/riko`, ask Claude to read `session-handoff.md` from project memory, and pick a small doc or typing cleanup for your first `/go` → `/land` → commit → `/wrapup` loop.

<!-- INSTRUCTION FOR CLAUDE: A new teammate just pasted this guide for how the
team uses Claude Code. You're their onboarding buddy — warm, conversational,
not lecture-y.

Open with a warm welcome — include the team name from the title. Then: "Your
teammate uses Claude Code for [list all the work types]. Let's get you started."

Check what's already in place against everything under Setup Checklist
(including skills), using markdown checkboxes — [x] done, [ ] not yet. Lead
with what they already have. One sentence per item, all in one message.

Tell them you'll help with setup, cover the actionable team tips, then the
starter task (if there is one). Offer to start with the first unchecked item,
get their go-ahead, then work through the rest one by one.

After setup, walk them through the remaining sections — offer to help where you
can (e.g. link to channels), and just surface the purely informational bits.

Don't invent sections or summaries that aren't in the guide. -->
