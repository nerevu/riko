# Reference-Data Consolidation Gameplan

## 1. Mission

Give riko's static currency and location tables a **single internal source of truth**
(`riko/_reference.py`) while keeping `riko.currencies` and `riko.locations` as thin,
public compatibility facades. This is a maintainability refactor, not a behavior change:
`LOCATIONS`, `CURRENCY_CODES`, and `CURRENCY_SYMBOLS` must be byte-for-byte equivalent
before and after.

It is **not** a runtime defect and does **not** gate the `features` → `main` merge — no
pipe misbehaves today. It maps onto the correctness taxonomy only as **C6** (redundant
weaker duplicates: three data files nobody reads) and a documentation-clarity item; see
[correctness-audit.md](correctness-audit.md). Keep it out of the R-register.

## 2. Current state (verified)

The three files under `riko/data/` are **already dead** — no Python imports them:

| File | Shape | Live consumer |
|---|---|---|
| `riko/data/countries.csv` | `continent,code_2,code_3,num,name` (countries only; **no continent rows**) | none |
| `riko/data/currencies.csv` | `code,location` | none |
| `riko/data/currencies.json` | rich metadata incl. `decimal_digits`/`rounding`; **no `location`, no `locale`** | none |

The behavioral source of truth is the two hand-maintained runtime dicts:

- `riko/locations.py::LOCATIONS` — keyed by continent **and** country. The 6 continent
  records (`code_2`/`continent` only) exist **only here**; `countries.csv` has no
  continent rows to regenerate them from.
- `riko/currencies.py::CURRENCY_CODES` (code → record) + `CURRENCY_SYMBOLS`
  (symbol → code). `CURRENCY_CODES` already merges location, display metadata, and the
  runtime-important `locale`, which `currencies.json` lacks entirely.

Two consumers anchor the behavior to lock:

- `riko/cast.py:188` `cast_location` joins a currency's `location` into `LOCATIONS` via a
  **tolerant** `LOCATIONS.get(location, {})` — a miss (e.g. EUR's `"European Union"`,
  which is neither continent nor country) degrades to no enrichment, by design.
- `riko/modules/currencyformat.py:72` reads the default locale from
  `CURRENCY_CODES.get(currency, {})` and hands it to Babel — Babel owns the formatting
  rules, so `decimal_digits`/`rounding` are not needed downstream.

## 3. Types are load-bearing and stay as-is

`riko/types/values.py` defines both as `TypedDict(total=False)`:

- `Region` — `Required[code_2]`, `Required[continent]`, optional `code_3`/`country`/`num`.
  The optional trio is **intentional**: the one type covers both the continent shape and
  the country shape. Do **not** "fix" it into a union or split it into `CountryRegion`
  during this refactor — that is an unrelated type-system change. Add a docstring line:
  *"Country records always contain all five fields; the optional keys accommodate the
  continent shape."*
- `CurrencyCode` — `Required[code]`, `Required[location]`, everything else optional
  (a handful of withdrawn currencies omit `locale`/name/symbol — `EEK`, `HRK`, `LTL`,
  `LVL`, `VEF`, `ZMK`, `ZWL`).

## 4. Known data deviations to whitelist (not silently fix)

The invariant tests (§5) must treat these existing runtime values as the baseline; a
refactor that "corrects" them is out of scope and would change output:

- Country name aliases that don't round-trip key↔`country`: `"Gambia the"`,
  `"Netherlands the"`, `"Philippines the"`, `"Marshall Islands the"`.
- `"Suricountry"` (a mangled `"Suriname"`) — key **and** `country` field.
- `LOCATIONS["Saint Vincent and the Grenadines"]["country"]` has doubled internal spaces
  (`"...and the   Grenadines"`).
- `"Spratly Islands"` carries literal string `"null"` for `code_3` and `num`.
- No continent-shaped `"Antarctica"` exists; `LOCATIONS["Antarctica"]` is the **country**
  record (`code_2=AQ`, `code_3=ATA`, `continent="Antarctica"`). The merge policy must
  preserve exactly this — see §6.

## 5. Phase RD0 — lock the contracts first

Add focused invariant tests **before** moving anything (`tests/internal/`), asserting:

- every country record has `code_2`/`code_3`/`continent`/`country`/`num`; every continent
  record has exactly `code_2`/`continent`;
- country key == `country` field, **except** the §4 whitelist;
- `CURRENCY_CODES[k]["code"] == k` for all `k`;
- every `CURRENCY_SYMBOLS` value exists in `CURRENCY_CODES` (`$→USD`, `£→GBP`, `€→EUR`,
  `₹→INR`);
- representative `cast_location()` behavior: a currency whose `location` resolves (e.g.
  `"United States"` → merged region) **and** one that does not (`EUR`/`"European Union"`
  → currency record unchanged);
- representative `currencyformat` locale selection, including a code missing `locale`.

Commit: `[TEST] Lock currency and location data invariants`.

## 6. Phase RD1 — the canonical module

Create `riko/_reference.py` with **separate** `CONTINENTS`, `COUNTRIES`,
`CURRENCY_CODES`, `CURRENCY_SYMBOLS` constants, then derive the combined map:

```python
CONTINENTS: dict[str, Region] = {...}   # the 6 continent records
COUNTRIES: dict[str, Region] = {...}    # the full ISO country records
LOCATIONS: dict[str, Region] = {**CONTINENTS, **COUNTRIES}
```

Rules:

- **Static Python data, no import-time CSV/JSON parsing** — one typed source, no
  package-resource I/O, no generated/runtime sync problem. (This is deliberately unlike
  the `gen-*` codegen surfaces; `_reference.py` is hand-maintained, not generated.)
- Keeping `CONTINENTS`/`COUNTRIES` separate makes the two `Region` shapes explicit and
  makes the Antarctica collision policy *code*, not merge-order accident: there is no
  continent Antarctica, so `{**CONTINENTS, **COUNTRIES}` yields the country record — lock
  it with the §4 regression assertion.
- **Do not derive `CURRENCY_SYMBOLS` mechanically.** `$` maps to several currencies;
  symbol→code must stay a small explicit preference map.
- Reconcile the three legacy representations **against the runtime dicts as the baseline**,
  not the files. Treat `decimal_digits`/`rounding` from `currencies.json` as **dropped on
  purpose** (not in `CurrencyCode`; Babel supplies formatting) unless a consumer is shown
  to need them.

Then reduce the facades to re-exports so every existing import keeps working
(`from riko.currencies import CURRENCY_CODES`, `from riko.locations import LOCATIONS`,
consumed by `cast.py`/`currencyformat.py`):

- `riko/currencies.py` → re-export `CURRENCY_CODES`, `CURRENCY_SYMBOLS` from `_reference`.
- `riko/locations.py` → re-export `LOCATIONS`. Keep the continent/country docstring,
  adjusted to say the records now originate in `_reference`.

Commit: `[REFACTOR] Consolidate currency and location reference data`.

## 7. Phase RD2 — delete the dead files

Because §2 established the files are unreferenced, deletion is low-risk. Still, before
removing, run a one-off comparison that reports keys/values unique to each file vs the
runtime dicts, so anything worth salvaging is a deliberate keep, not a silent loss. Do
**not** require every currency `location` to resolve through `LOCATIONS` (EUR's
`"European Union"` legitimately does not; `cast_location` tolerates it).

Remove `riko/data/countries.csv`, `riko/data/currencies.csv`,
`riko/data/currencies.json`.

Commit: `[CLEANUP] Remove duplicate currency and country data files`.

## 8. Definition of done

1. `_reference.py` is the only place currency/location data is defined; `currencies.py`
   and `locations.py` are re-export facades.
2. `LOCATIONS`, `CURRENCY_CODES`, `CURRENCY_SYMBOLS` are provably unchanged (before/after
   equality check + the RD0 invariants pass).
3. `Region`/`CurrencyCode` are untouched; the two-shape `Region` is documented, not
   redesigned.
4. The three `riko/data/` files are gone and nothing imports them.
5. Full pytest + doctest + Pyright + Ruff green.

## 9. Ownership

`reference-data.md` owns the currency/location reference tables and their facades.
[enrichment-modules.md § 6b](enrichment-modules.md) keeps geolocate's `currency` lookup
(the only real `type`), which *consumes* `CURRENCY_CODES` but does not own it. Types stay
owned by `riko/types/values.py`. See [ownership.md](ownership.md).
