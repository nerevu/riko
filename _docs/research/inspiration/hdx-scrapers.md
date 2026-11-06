---
source: ../../../../HDX/scrapers/README.md
---

# HDX Scrapers

A collection of data collectors ("scrapers") for the
[Humanitarian Data Exchange (HDX)](https://data.hdx.rwlabs.org/). Each scraper fetches
data from an external humanitarian source, normalizes it, and produces CSV/SQLite output
suitable for upload to HDX.

## Scrapers

| Directory | Source | Description |
| --- | --- | --- |
| [`hdxscraper-acled`](hdxscraper-acled/) | [ACLED Realtime Data](http://www.acleddata.com/data/realtime-data-2015/) | Armed Conflict Location & Event Data collector. |
| [`hdxscraper-fao`](hdxscraper-fao/) | [FAO](http://faostat3.fao.org) | FAO food aid shipments, food security, prices, and price indices collector. |
| [`hdxscraper-fts`](hdxscraper-fts/) | [UN OCHA FTS API](https://fts.unocha.org/) | Financial Tracking Service appeals, emergencies, and clusters collector. |
| [`hdxscraper-who`](hdxscraper-who/) | [WHO GHO](http://apps.who.int/gho/data/node.main.132?lang=en) | WHO Global Health Observatory climate-change indicators collector. |
| [`hdxscraper-world-bank-climate`](hdxscraper-world-bank-climate/) | [World Bank Climate Change Data](http://sdwebx.worldbank.org/climateportal/) | World Bank climate change data collector. |
| [`undp/hdxscraper-hdro`](undp/hdxscraper-hdro/) | [UNDP HDRO](http://hdr.undp.org/en/data) | UNDP Human Development Report Office (HDRO) API collector. |
| [`undp/hdxscraper-undp-climate`](undp/hdxscraper-undp-climate/) | [Oxford / UNDP Climate Change Country Profiles](http://www.geog.ox.ac.uk/research/climate/projects/undp-cp/) | Observed precipitation time series per country. |
| [`undp`](undp/) (`update`, `upload`) | Local HDR CSV files | Bash scripts that push the 20 Human Development Report CSVs in `undp/` to CKAN. |
| [`guinea-IPC-data`](guinea-IPC-data/) | Guinea IPC cluster spreadsheets | Shell workflow that HXL-tags and merges Guinea IPC health training reports (see its `README.txt`). |
| [`hdxscraper-cordaid`](hdxscraper-cordaid/) | [IATI Datastore](http://datastore.iatistandard.org/) | **Deprecated.** Cordaid IATI activity data collector. |
| [`unhabitat/hdxscraper-unhabitat`](unhabitat/hdxscraper-unhabitat/) | [devinfo urbaninfo](http://www.devinfo.org/urbaninfo/) | **Deprecated.** UN Habitat urbaninfo indicator collector. |
| [`migrant-deaths`](migrant-deaths/) | [IOM Missing Migrants](http://missingmigrants.iom.int/) | **Deprecated.** Scrapes the IOM Missing Migrants monthly fatalities table. |
| [`un-casualty`](un-casualty/) | [UNAMI](http://www.uniraq.org/) | **Deprecated.** Scrapes UNAMI Iraq monthly casualty figures. |

Deprecated scrapers are unmaintained; their READMEs list known breakage.

## Two styles of scraper

Most scrapers fall into two groups. The `undp/` bash scripts and `guinea-IPC-data` fit
neither; see their own READMEs.

### 1. `hdxscraper-*` — Flask/SQLAlchemy apps

These include the top-level `hdxscraper-*` directories plus `undp/hdxscraper-hdro`,
`undp/hdxscraper-undp-climate`, and `unhabitat/hdxscraper-unhabitat`. They are
[ScraperWiki](https://scraperwiki.com/)-style apps built on Flask, Flask-SQLAlchemy, and
[`manage.py`](https://github.com/reubano/manage.py). They share a common layout:

```text
app/          # models.py, utils.py — data model and extraction logic
bin/          # setup, populate helper scripts
datasets/     # dataset metadata
tests/        # tests
config.py     # configuration
manage.py     # task runner
requirements.txt
```

Not every project has every entry: `undp/hdxscraper-undp-climate` uses a single `app.py`
instead of `app/`; `hdxscraper-cordaid`, `hdxscraper-world-bank-climate`, and
`undp/hdxscraper-undp-climate` have no `datasets/`; and `unhabitat/hdxscraper-unhabitat`
has an empty one.

**Setup**

> Use a [virtualenv](https://virtualenv.pypa.io/).

```sh
pip install -r requirements.txt
manage setup
```

Only `hdxscraper-fts` also has a `manage init` command; see its README.

**Run**

```sh
manage -m Production run
```

`manage` defaults to `-m Development`, which caps the number of rows fetched
(`ROW_LIMIT` in `config.py`), so use `-m Production` for a full run. Results are written
to a SQLite database (`scraperwiki.sqlite`). On a ScraperWiki Box, use `make setup` and
`manage -m Scraper run`. For output columns and source-specific details, see each
scraper's own `README.md` and its `app/models.py` or `config.py`.

### 2. `migrant-deaths`, `un-casualty` — standalone scripts

These are single-file scripts that scrape an HTML table with `requests` +
`BeautifulSoup` and write CSV.

```sh
pip install -r requirements.txt

# migrant-deaths: no arguments; writes data.csv and metadata.csv next to the script
./scrape

# un-casualty: requires an output CSV path
./scrape data.csv
```

## Requirements

- Python 2.7 (the scrapers target the Python 2 era ScraperWiki platform)
- Per-scraper dependencies in each `requirements.txt`

## License

Each `hdxscraper-*` project is MIT licensed; see the `LICENSE` file within its
directory. `migrant-deaths`, `un-casualty`, `guinea-IPC-data`, and the `undp/` scripts
ship no `LICENSE` file.
