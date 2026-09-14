# extractor

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

`extractor` is an async command-line tool for building a government-contracting sales
pipeline. It **parses** procurement opportunity pages, **enriches** the companies and
contacts it finds against a range of data providers, **cleans** the results, and
**upserts** them into Airtable.

## Pipeline

```
parse opportunity  ->  enrich companies/contacts  ->  clean  ->  upsert to Airtable
   (bonfire, ...)        (SAM, HigherGov, ...)                     (Companies, People, ...)
```

### Opportunity / enrichment sources

The `enrich` command's `--source` selects a parser:

- `bonfire` — Bonfire procurement portal opportunities
- `bidnet` — BidNet opportunities
- `arpa`, `arpa-alt` — ARPA opportunity listings
- `company` — enrich an existing CSV of companies (no scrape)

When enriching companies, data is gathered from many providers (toggle with
`--allowed` / `--denied`), including SAM.gov (`sam`), DSBS (`dsbs`),
HigherGov (`highergov_api`, `highergov_html`), Apollo (`apollo`), Clearbit
(`clearbit*`), Marcom Robot (`marcom_robot`), LinkedIn (`linkedin`), FPDS, and the
Illinois Comptroller.

### Airtable destinations

`--destination` chooses the target table:

| Value | Airtable table |
| ----- | -------------- |
| `companies` | Companies |
| `people` | People |
| `positions` | People Positions |
| `partners` | Project Partners |

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

```
HIGHERGOV_API_KEY=...
HIGHERGOV_USERNAME=...
HIGHERGOV_PASSWORD=...
AIRTABLE_API_KEY=...
MARCOM_ROBOT_API_KEY=...
SAM_API_KEY=...
CLEARBIT_API_KEY=...
APOLLO_API_KEY=...
```

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

Key options: `-s/--source`, `-d/--destination`, `-u/--url`, `-o/--out`,
`-a/--allowed` / `-D/--denied` (providers), `-S/--subdomain`, `-q/--query` (filter),
`-l/--limit`, `-f/--offset`, `-h/--shuffle`, `-c/--use-cache`,
`-O/--overwrite`, `-F/--force`, `-Q/--quote`, `-i/--id`, `-A/--output-all`.

### `clean`

Normalize an existing CSV (company-name/domain cleanup, field formatting) without
scraping or upserting:

```bash
extractor clean data/enriched.csv -d companies -o data/clean.csv
```

### `upsert`

Push a cleaned CSV into the chosen Airtable table:

```bash
extractor upsert data/enriched.csv --id
```

## How it works

- **Async HTTP** via `httpx` (HTTP/2), with response caching in a local
  `extractor.sqlite` store through [`hishel`](https://hishel.com/) (enable with
  `--use-cache`).
- **Browser automation** via [Playwright](https://playwright.dev/python/) for sources
  that require rendering or login; rotating user agents are read from `agents.json`.
- Company names are normalized (suffix stripping), domains derived from websites/email
  domains, and personal email domains filtered out before upserting.

## Development

```bash
pytest          # run tests
ruff check .    # lint
```
