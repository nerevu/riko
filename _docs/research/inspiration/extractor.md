---
source: ../../../../extractor/README.md
---

# extractor

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

`extractor` is an async command-line tool for building a government-contracting sales
pipeline. It **parses** procurement opportunity pages, **enriches** the companies and
contacts it finds against a range of data providers, **cleans** the results, and
**upserts** them into Airtable.

## Pipeline

```text
parse opportunity  ->  enrich companies/contacts  ->  clean  ->  upsert to Airtable
   (bonfire, ...)        (SAM, HigherGov, ...)                     (Companies, People, ...)
```

### Opportunity / enrichment sources

The `enrich` command's `--source` selects a parser (default `bonfire`):

- `bonfire` — Bonfire procurement portal opportunities
- `bidnet` — BidNet opportunities
- `arpa`, `arpa-alt` — ARPA opportunity listings
- `company` — enrich an existing CSV of companies (no scrape)

With `--url`, the source is detected from the URL's host name: the first source key
that appears in the second-level name wins (`cps.bonfirehub.com` → `bonfire`), and the
first label becomes `--subdomain` (`cps`). `arpa-alt` is never auto-detected, because
`arpa` matches first; pass `-s arpa-alt` with a saved page instead.

The data providers below run only with `-s company`. The opportunity sources write the
rows they parse (Bonfire also fetches each document taker's details); run `enrich -s
company` on such a file to enrich the companies.

When enriching companies, data is gathered from many providers (toggle with
`--allowed` / `--denied`), including SAM.gov (`sam`), DSBS (`dsbs`),
HigherGov (`highergov_api`, `highergov_html`), Apollo (`apollo`), Clearbit
(`clearbit*`), Marcom Robot (`marcom_robot`), LinkedIn (`linkedin`), FPDS, and the
Illinois Comptroller.

### Providers

`--allowed` and `--denied` take these keys. Each company is enriched by a chain of
providers: extractor picks one, merges what it returns into the company, and then picks
again with the updated record.

Key | Used when the company has | Skipped once the company has | Default | Credentials
---|---|---|---|---
`done` | all of `uei`, `sam_registration`, `company_name`, `legal_name`, `domain`, `website`, `highergov_id`, `awardee_type`, `federal_awards_2023`, `federal_awards_2024`, `poc_name`, `clearbit_id`, `apollo_poc_id`, `description`, `connections` | (never) | on | none; prints "already enriched" and ends the chain
`urlify` | `website` or `domain` | an `https` website whose domain matches `domain` | on | none
`clearbit` | `domain` and `website` | `clearbit_id` | **denied** | `CLEARBIT_API_KEY`
`marcom_robot` | a name | `domain` | **denied** | `MARCOM_ROBOT_API_KEY`
`clearbit_alt` | a name | `domain` | **denied** | none
`clearbit_alt2` | a name | `domain` | **denied** | `CLEARBIT_API_KEY`
`html` | `website` | `company_name`, `description`, and `services` | **denied** | none
`linkedin` | `linkedin` | `connections` | on | none
`sam` | `uei`, or a name plus either `domain` and `website` or email domains | `sam_registration` | on | `SAM_API_KEY`
`dsbs` | `uei` | `dsbs_id` | on | none
`apollo` | `domain`, `website`, `poc_name`, and a name | `apollo_poc_id` | **denied** | `APOLLO_API_KEY`
`highergov_api` | `uei` or a HigherGov id | `highergov_id` | on | `HIGHERGOV_API_KEY`
`highergov_html` | `highergov_url` | `awardee_type` | on | `HIGHERGOV_USERNAME`, `HIGHERGOV_PASSWORD` (browser sign-in)
`fpds_2023`, `fpds_2024` | `uei` | `federal_awards_2023` / `federal_awards_2024` | on | none
`il_comptroller_2024` | a name | (never) | on | none
 `il_comptroller_2023` | (intended; accepted by `-a`/`-D` but not implemented, so it has no effect) |  |  |  |

"A name" is `legal_name` or `company_name`, with commas and periods removed.

Selection rules:

- Providers are tried in the order of the table.
- With `--allowed`, only the listed providers are candidates. `--denied` providers are
  then skipped. The default deny list is `apollo`, `html`, `marcom_robot`, `clearbit`,
  `clearbit_alt`, and `clearbit_alt2`. Giving `-D` replaces that list, so `-a apollo`
  alone still skips Apollo; use `-a apollo -D html` (and so on) to re-enable it.
- The first candidate whose requirements hold and that isn't skipped wins. `--force`
  ignores the "Skipped once" column, so providers run again for companies that already
  have the field.
- A provider can name a fallback (`marcom_robot` → `clearbit_alt`). When its request
  fails and can't be retried soon, the next round tries the fallback first. `sam` names
  `highergov`, which isn't a provider key, so the next round falls back to normal
  selection.
- After more than `MAX_RETRIES` (2) retries against a host for one company, that
  provider is skipped for the company.

Merge rules, applied to each provider response:

- Empty values (empty strings and the string `None`) in the response are ignored.
- `services`, `naics_codes`, and `industries_served` are joined with commas;
  `employee_count` keeps the larger bucket; `description` keeps the longer text.
- With `--overwrite`, the remaining response values replace the company's. Without it,
  they only fill fields that are missing or empty.

### Airtable destinations

`--destination` chooses the target table (default `companies`). All tables live in the
Airtable base `appryXtUymto74NnU`, which is set in the code.

| Value | Airtable table | Upsert merge key | Merge key with `--id` |
| ----- | -------------- | ---------------- | --------------------- |
| `companies` | Companies | `Company Name` | `ID` |
| `people` | People | `Primary Work Email` | `ID` |
| `positions` | People Positions | `Work Email` | `ID` |
| `partners` | Project Partners | `Opportunity` + `Contact Email` | `ID` |

### Fields

`enrich` and `clean` write CSV columns named after the destination table's Airtable
fields. `enrich -s company` and `clean` read input columns by their internal key;
headers are normalized first
(lowercased, spaces and hyphens become `_`, parentheses and `?` are removed), so most
Airtable column names are accepted too. Columns with no mapping are dropped with a
warning.

`people`:

Internal key | Airtable field
---|---
`poc_name` | Name
`poc_email` | Primary Work Email
`phone` | Primary Work Phone
`linkedin` | Linkedin
`location` | Location

`partners`:

Internal key | Airtable field
---|---
`company_name` | Contact Org
`poc_name` | Contact Person
`poc_email` | Contact Email
`file_count` | File Count
`description_of_research_focus_area` | Strengths
`description_of_teaming_partner` | Needs
`technical_areas` | Technical Areas

`positions`:

Internal key | Airtable field
---|---
`company_name` | Employer
`poc_name` | Person
`poc_email` | Work Email
`phone` | Work Phone
`title` | _Title

`companies`: `company_name` → Company Name, `legal_name` → Legal Name, `dba` → dba,
`abbreviation` → Abbreviation, `plural_name` → Plural Name, `id` → ID (written only with
`--id`), `website` → Website, `domain` → _domain, `employee_email_domains` → Employee
email domains, `email` → Email, `phone` → Phone, `address` → Address, `zipcode` →
Zipcode, `location` → Location, `country` → Country, `description` → Description,
`services` → Services, `industries_served` → Industries Served, `primary_industry` →
Primary Industry, `primary_naics` → Primary NAICS, `naics_codes` → NAICS Codes,
`employee_count` → Employee Count, `linkedin` → Linkedin, `logo` and `logo_url` → Logo
URL, `parent_org` → Parent Org, `type` → Type, `level` → Level, `sub_type` → Sub-Type,
`uei` → UEI, `sam_registration` → Sam Registration, `dsbs_id` → DSBS ID, `dsbs_status` →
DSBS Status, `capabilities_statement_url` → Capabilities Statement URL,
`certs_&_vehicles` → Certs & Vehicles, `highergov_id` → Highergov ID, `highergov_url` →
Highergov URL, `awardee_type` → Awardee Type, `parent_awardee` → Parent Awardee,
`federal_awards_2023` → Federal Awards (2023), `federal_awards_2024` → Federal Awards
(2024), `federal_contracts_2023` → Federal Contracts (2023), `federal_contracts_2024` →
Federal Contracts (2024), `apollo_id` → Apollo ID, `clearbit_id` → Clearbit ID,
`marcom_robot_score` → Marcom Robot Score. `cb_employee_count` or `hg_employee_count` is
converted to an Employee Count bucket (for example `251-1K` → `201-500`).

Values are cleaned on the way out: whitespace and newlines collapse to single spaces;
`website`, `logo_url`, `highergov_url`, and `domain` are lowercased with any trailing
`/` removed; `services`, `naics_codes`, and `industries_served` become comma-separated
lowercase slugs; a `linkedin` value starting with `company/` gets the
`https://www.linkedin.com/` prefix.

## Installation

Requires Python ≥ 3.11.7. Install from source with [flit](https://flit.pypa.io/):

```bash
git clone https://github.com/reubano/extractor
cd extractor
python -m venv venv && source venv/bin/activate
pip install -e '.[test,dev]'

# Playwright is used for browser-based scraping — install its browser
playwright install
```

## Configuration

The tool reads API credentials from a `.env` file in the project root:

```text
HIGHERGOV_API_KEY=...
HIGHERGOV_USERNAME=...
HIGHERGOV_PASSWORD=...
AIRTABLE_API_KEY=...
MARCOM_ROBOT_API_KEY=...
SAM_API_KEY=...
CLEARBIT_API_KEY=...
APOLLO_API_KEY=...
```

Variable | Used by
---|---
`HIGHERGOV_API_KEY` | the `highergov_api` provider
`HIGHERGOV_USERNAME`, `HIGHERGOV_PASSWORD` | the `highergov_html` provider, when HigherGov asks the browser to sign in
`AIRTABLE_API_KEY` | `upsert`
`MARCOM_ROBOT_API_KEY` | the `marcom_robot` provider (denied by default)
`SAM_API_KEY` | the `sam` provider
`CLEARBIT_API_KEY` | the `clearbit` and `clearbit_alt2` providers (denied by default)
`APOLLO_API_KEY` | the `apollo` provider (denied by default)

A missing variable is read as an empty string, so that provider's requests go out
without valid credentials.

Run `extractor` from the project root. These files are found relative to the current
directory:

- `agents.json`: user agents; one is picked at random per run. It is read at start-up,
  so the command fails in any other directory.
- `extractor.sqlite`: the HTTP cache (`--use-cache`).
- `playwright/.auth/auth.json`: saved browser sign-in state.

> **Security:** the `.env` committed to this repo contains live API keys. Rotate them
> and keep credentials out of version control.

## Usage

For help:

```bash
extractor --help          # or: python -m extractor --help
extractor enrich --help
```

### `enrich`

Parse an opportunity URL (or an input file / STDIN) and enrich the results. Use `-` as
the file argument to read from a URL or STDIN.

```bash
# Enrich a CSV of companies against SAM, caching HTTP responses
extractor enrich data/to_enrich.csv -s company --overwrite --use-cache --id \
    -o data/enriched.csv --allowed sam

# Parse a Bonfire opportunity into the Project Partners table
extractor enrich - -d partners \
    --url "https://cps.bonfirehub.com/opportunities/142898" \
    --use-cache -o data/142898.csv
```

With `--url`, the file argument is ignored. Without it, a `company` source reads a CSV
of companies (each row needs `company_name` or `domain`); any other source reads a saved
opportunity page.

Key options:

Option | Default | Effect
---|---|---
`-s/--source` | `bonfire` | parser; see [sources](#opportunity--enrichment-sources)
`-d/--destination` | `companies` | Airtable table whose field names the output uses
`-u/--url` | | opportunity URL; also sets `--source` and `--subdomain` from the host
`-o/--out` | STDOUT | output CSV
`-a/--allowed` | all | providers to consider (repeatable); see [Providers](#providers)
`-D/--denied` | `apollo`, `html`, `marcom_robot`, `clearbit`, `clearbit_alt`, `clearbit_alt2` | providers to skip (repeatable; replaces the default)
`-S/--subdomain` | `cookcountyil` | portal subdomain passed to the parser
`-q/--query` | | keep only companies whose `company_name` contains this text (case-insensitive); `-s company` only
`-l/--limit` | | process at most this many companies; `-s company` only
`-f/--offset` | | skip this many companies first; `-s company` only
`-h/--shuffle` | off | with `-l`, a random sample of that size (`-f` is ignored); with neither `-l` nor `-f`, a random order; `-s company` only
`-c/--use-cache` | off | cache HTTP responses; see [How it works](#how-it-works)
`-O/--overwrite` | off | provider values replace existing ones; see the merge rules
`-F/--force` | off | run providers even for fields the company already has
`-Q/--quote` | off | prefix `naics_codes`, `location`, and the employee count with `'` so spreadsheets keep them as text
`-i/--id` | off | write the `ID` column (a generated UUID for rows without one), for a later `upsert --id`
`-A/--output-all` | off | also write the input companies that produced no output row

The output CSV is written when the run ends (or on Ctrl-Z), not row by row. Its columns
are the destination's Airtable field names (see [Fields](#fields)), in no fixed order.

### `clean`

Normalize an existing CSV (company-name/domain cleanup, field formatting) without
scraping or upserting:

```bash
extractor clean data/enriched.csv -d companies -o data/clean.csv
```

(intended; broken today) The output keeps only the `dba` column for `companies` and no
columns for the other tables, because the rows are mapped to Airtable field names twice
and the second pass drops every name it doesn't know. `-Q/--quote` has no effect on
`clean`. Options: `-o/--out` (default STDOUT), `-d/--destination` (default
`companies`), `-Q/--quote`, `-i/--id`.

### `upsert`

Push a cleaned CSV into the chosen Airtable table:

```bash
extractor upsert data/enriched.csv --id
```

The input must use Airtable field names, as `enrich` writes them; columns are sent to
Airtable as-is. Before sending:

- empty values and the string `None` are dropped;
- the computed fields `Employee email domains` and `Plural Name` are dropped;
- `Location` is sent as a one-item linked-record list.

Rows go to the Airtable base `appryXtUymto74NnU` in batches of 10, as upserts merged on
the table's merge key ([Airtable destinations](#airtable-destinations)), or on `ID` with
`--id`. Airtable's `typecast` is on, so text values are converted to the field types.
Rerunning with the same input updates the same records.

Options: `-d/--destination` (default `companies`), `-i/--id`, and `-q/--query`,
`-l/--limit`, `-f/--offset`, `-h/--shuffle` with the same meaning as for `enrich`
(`-q` matches the table's company-name column: Company Name, Contact Org, or Employer).
Use `-` to read from STDIN.

## How it works

- **Async HTTP** via `httpx` (HTTP/2), with response caching in a local
  `extractor.sqlite` store through [`hishel`](https://hishel.com/) (enable with
  `--use-cache`). Cached responses never expire, are reused without revalidation, and
  include `422` error responses, so a cached request is never sent again. Delete
  `extractor.sqlite` to refetch. The cache covers provider requests and the Bonfire
  parser's requests; the `--url` page itself is always fetched.
- **Browser automation** via [Playwright](https://playwright.dev/python/) for sources
  that require rendering or login; rotating user agents are read from `agents.json`.
- Company names are normalized (suffix stripping), domains derived from websites/email
  domains, and personal email domains filtered out before upserting:
  - a name ending in a suffix such as `LLC`, `Inc`, `Corp`, `Co`, `Ltd`, `Limited`,
    `PLC`, `GmbH`, `LLP`, or `L.P.` becomes `legal_name`, and `company_name` is the name
    without it;
  - a `website` starting with `www` gets `http://`;
  - `domain` comes from `website`, or else from the only non-personal email domain;
    `gmail.com`, `yahoo.com`, `hotmail.com`, `aol.com`, and `outlook.com` are personal;
  - a `domain` that isn't among the email domains, or several email domains, is reported
    as an error.

### Exit status and side effects

- The command exits `1` if any error was collected (including the domain checks above),
  even when it wrote output; otherwise `0`.
- On an unexpected error, the command opens the Python debugger (`breakpoint()` and a
  `pdb` post-mortem) instead of exiting, so it isn't suited to unattended runs.
  `PYTHONBREAKPOINT=0` disables the `breakpoint()` calls only. The debugger also opens
  on data conditions, including a URL field containing a space, a company row with
  neither name nor domain, a `website` containing `external`, a HigherGov id that
  doesn't match its URL, a provider error response, and any failed Airtable request.
- Ctrl-Z writes the output collected so far and exits, instead of suspending.

## Development

```bash
pytest          # run tests
ruff check .    # lint
```

The test suite has one test, a `--version` smoke test (`tests/test_extractor.py`).

## Known issues

- `clean` drops nearly every column, and ignores `--quote` (`cli.py:543`, `:556-561`,
  `:200-208`).
- `upsert -d people -q ...` fails with a `KeyError`, because the People mapping has no
  company-name column (`cli.py:375`, `config.py:226-232`).
- `il_comptroller_2023` is accepted by `-a`/`-D` but has no provider (`_types.py:70`;
  `get_sources` in `__init__.py`).
- `sam`'s fallback `highergov` isn't a provider key (`__init__.py:800`).
- The command fails outside the project root, because `agents.json` is read from the
  current directory at import (`config.py:16-21`, `:278`).
- Errors drop into the debugger (`cli.py:82`, `:483`, `:514`; `__init__.py:1152`).
- `pyproject.toml` declares the MIT license; the project is licensed under Apache 2.0
  (`LICENSE`).

## License

`extractor` is distributed under the [Apache License 2.0](LICENSE).
