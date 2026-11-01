# Upstream fixes gameplan

This file is the one owner for defects and gaps in riko's dependencies that riko works around
locally. Each entry names the dependency defect, the riko workaround, the canary test that
detects the dependency fix, and what riko deletes once that fix ships. Semantics that a feature
gameplan owns (conversion helpers in `database-transforms.md`, cache behavior in `cache.md`,
CSV writing in `artifact-conversion.md`) stay there; this file only tracks the dependency side.

## How tracking works

- **Canaries call the dependency directly.** Every defect riko works around has a strict-xfail
  test in `tests/internal/test_upstream.py` that calls the dependency, never riko, and asserts
  the behavior riko needs. A test through riko would pass already, because the workaround hides
  the defect. When a dependency release fixes the defect, the canary passes unexpectedly and
  fails the run.
- **A new locked meza version is the trigger, and the sync is automatic.** riko resolves meza
  from PyPI releases only (`INTERNALS.md`, meza bullet). Whenever `uv.lock` moves meza, `/land`
  runs the canaries; each unexpected pass raises the `meza>=` floor to that release and deletes
  the workaround, its canary, and its entry here. Nobody edits this file by hand.
- **A defect with no workaround** (riko lives with it) keeps its canary or tripwire where the
  owning gameplan put it and gets an entry here that points at it.
- **Upstream work** happens in the dependency's own repository. Each entry's branch/PR line is
  refreshed in the same `/land` step from the meza checkout's branches and open pull requests,
  so a fix that is written but not yet released is not lost.
- **A new workaround adds an entry and a canary in the same change.** `/triage` routes
  dependency defects here.

## meza

Local checkout: `~/Documents/Projects/meza`. Releases go to PyPI; riko's floor is `meza>=0.47.1`.

### 1. `read_csv` raises on an empty source

- **Defect:** `meza.io.read_csv` on an empty source raises `RuntimeError: generator raised
  StopIteration`; its `reader` calls `next(f)` on the empty file (`meza/io.py`, `reader`).
- **Workaround:** `gen_rows` (`riko/io/_sync.py`) drops that error before the first row; the
  `csv` and `fetchtable` readers both wrap their meza rows in it.
- **Canary:** `tests/internal/test_upstream.py::TestMeza::test_read_csv_yields_nothing_for_an_empty_source`.
- **Delete on fix:** `gen_rows` and its four call sites; keep
  `tests/internal/test_modules.py::TestCsvParser::test_empty_csv_yields_no_rows`.
- **Upstream branch/PR:** none yet.

### 2. `Reencoder` decoding, `read(n)`, and close

- **Defects:** with `remove_BOM=True`, latin-1 raises `UnicodeEncodeError` and UTF-16 raises
  `UnicodeError` (meza strips the BOM as a byte set from encoded bytes); a UTF-16-LE source
  loses every line after the first; `read(n)` ignores `n`; `close()` leaves the source open.
- **Workaround:** `Reencoder` (`riko/io/_reencode.py`) replaces meza's constructor, `read`, and
  `close` wholesale, with `gen_without_bom` (`riko/io/_reencode.py`) stripping the BOM from
  decoded text.
- **Canaries:** `tests/internal/test_upstream.py::TestMeza::test_reencoder_decodes_with_bom_removal`
  (one row per decoding defect) and
  `tests/internal/test_upstream.py::TestMeza::test_reencoder_close_closes_its_source`.
- **Delete on fix:** the overridden methods, once every row passes; the subclass may stay for
  riko's `owner=` close hook.
- **Upstream branch/PR:** none yet. The port is riko's `_decode`/`_gen_lines` logic.

### 3. `Objectify` has no length

- **Defect:** `len(meza.fntools.Objectify(...))` raises `TypeError`.
- **Workaround:** `Objectify.__len__` (`riko/coercion/_objectify.py`).
- **Canary:** `tests/internal/test_upstream.py::TestMeza::test_objectify_has_a_length`.
- **Delete on fix:** the `__len__` override.
- **Upstream branch/PR:** none yet.

### 4. `IterStringIO` lacks the buffer protocol

- **Defect:** `bytes()`/`memoryview()` on `meza.io.IterStringIO` raise `TypeError`.
- **Workaround:** `IterStringIO.__buffer__` (`riko/io/_reencode.py`).
- **Canary:** `tests/internal/test_upstream.py::TestMeza::test_iterstringio_supports_the_buffer_protocol`.
- **Delete on fix:** the `IterStringIO` subclass.
- **Upstream branch/PR:** none yet.

### 5. `records2csv(bom=True)` writes bytes into a text buffer

- **Defect:** `meza.convert.records2csv(..., bom=True)` raises `TypeError` for every encoding.
- **Workaround:** none; riko lives with it. CSV writing semantics are owned by
  `artifact-conversion.md`.
- **Tripwire:** `tests/public/test_write.py::TestExportFormats::test_csv_bom_is_written_in_the_given_encoding`.
- **Delete on fix:** the tripwire becomes a regular test.
- **Upstream branch/PR:** none yet.

### 6. meza ships no type information

- **Defect:** meza has no `py.typed` and no annotations.
- **Workaround:** hand-written stubs in `typings/meza/` (13 of their `pyright: ignore` comments
  cover meza's own method-override clashes), the `TYPE_CHECKING` stand-in for `Objectify` in
  `riko/coercion/_objectify.py`, the typed `chunk` pass-through (`riko/io/_async.py`), and the
  meza row casts in `csv.py`/`fetchtable.py` (whose
  removal R10 owns, `implementation-sequence.md`).
- **Canary:** `tests/internal/test_upstream.py::TestMeza::test_meza_ships_type_information`.
- **Delete on fix:** `typings/meza/` and the `Objectify` stand-in, after checking that meza's
  annotations satisfy riko's pyright and `--verifytypes` gates.
- **Upstream branch/PR:** none yet.

### 7. Helpers riko keeps that belong in meza

- **Gap:** `listize` (`riko/coercion/_sequences.py`), `cast_datetime` (`riko/coercion/cast.py`),
  and `group_by` (`riko/modules/_sortutils.py`) are general conversion helpers. Their target
  semantics are owned by `database-transforms.md` §25.
- **Canary:** none; these are features meza lacks, not defects.
- **Delete on fix:** each riko copy once meza ships its equivalent.
- **Upstream branch/PR:** none yet.

### 8. `records2json` writes sets in hash order

- **Defect:** `meza.convert.records2json` writes a set cell in iteration order, so the same
  items serialize differently from run to run (`PYTHONHASHSEED`-dependent for strings).
- **Workaround:** `records2json` and `_SortedSetEncoder` (`riko/io/_serialization.py`) replace
  meza's converter for the `json`/`jsonl` formats and write sets sorted.
- **Canary:** `tests/internal/test_upstream.py::TestMeza::test_records2json_writes_sets_sorted`.
- **Delete on fix:** riko's `records2json` and `_SortedSetEncoder`; register meza's converter
  in `CONVERSION_FUNCS` again (check its other options still match riko's sorted keys and
  non-ASCII output).
- **Upstream branch/PR:** none yet.

### 9. `chunk` splits a `str`/`bytes` into lists

- **Defect:** `meza.fntools.chunk` yields lists of characters for a `str` and lists of ints for
  `bytes`, while a file-like source yields `str`/`bytes` chunks. Fixing it changes meza's return
  shape for existing callers, so it needs a meza major-version decision.
- **Workaround:** `_chunk_content` (`riko/io/_async.py`) joins each list back into a `str` or
  `bytes`.
- **Canary:** `tests/internal/test_upstream.py::TestMeza::test_chunk_splits_a_str_into_strs`.
- **Delete on fix:** the join branches in `_chunk_content`.
- **Upstream branch/PR:** none yet.

## mezmorize

Cache behavior that belongs in mezmorize is owned by `cache.md`; no current riko workaround.
