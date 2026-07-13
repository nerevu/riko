# riko

Python stream processing engine modeled after Yahoo! Pipes.

## Key Paths

- `riko/bado/` — async layer (Twisted-based, anyio support planned)
- `riko/bado/__init__.py` — backend detection (`twisted` / `anyio` / `empty`)
- `riko/bado/io.py` — async file/URL I/O
- `riko/bado/itertools.py` — async itertools (`async_map`, `coop_reduce`, etc.)
- `riko/bado/util.py` — async utilities (`xml2etree`, `async_sleep`, etc.)
- `riko/bado/mock.py` — test reactor (`FakeReactor`)
- `riko/collections.py` — `SyncPipe`, `AsyncPipe`, `SyncCollection`, `AsyncCollection`
- `riko/modules/` — individual pipe implementations
- `riko/transform.py` — column transformation pipe factories (`coalesce_pipe`, `strip_url_pipe`, etc.) and `transform_columns` helper (planned; see ROADMAP Milestone 7)
- `riko/utils.py` — sync utilities
- `optional-requirements.txt` — Twisted, treq, lxml, speedparser3

## Async Backend

- Default backend: `twisted` (when installed), else `empty` (sync fallback)
- Backend selected via `RIKO_ASYNC_BACKEND` env var: `twisted` | `anyio`
- async/await conversion doc: `docs/ASYNC_AWAIT_CONVERSION.md` (prerequisite for anyio)
- anyio support design doc: `docs/ANYIO_SUPPORT.md`
- improvement roadmap: `docs/ROADMAP.md`
- modernization & optimization guide: `docs/optimize.md`

## Coding Style

- No comments unless logic is non-obvious
- Single return statement per function
- Return-based error handling, graceful degradation
- Guard optional imports with try/except and set `backend`/flag variables
