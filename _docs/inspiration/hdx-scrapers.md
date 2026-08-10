# HDX Scrapers

A collection of data collectors ("scrapers") for the [Humanitarian Data Exchange (HDX)](https://data.hdx.rwlabs.org/). Each scraper fetches data from an external humanitarian source, normalizes it, and produces CSV/SQLite output suitable for upload to HDX.

## Scrapers

| Directory | Source | Description |
| --- | --- | --- |
| [`hdxscraper-acled`](hdxscraper-acled/) | [ACLED Realtime Data](http://www.acleddata.com/data/realtime-data-2015/) | Armed Conflict Location & Event Data collector. |
| [`hdxscraper-cordaid`](hdxscraper-cordaid/) | [Cordaid Open Data](https://www.cordaid.org/en/vision-open-data/) | Cordaid IATI activity data collector. |
| [`hdxscraper-fao`](hdxscraper-fao/) | [FAO](http://faostat3.fao.org) | FAO food aid shipments and food security data collector. |
| [`hdxscraper-fts`](hdxscraper-fts/) | [UN OCHA FTS API](https://fts.unocha.org/) | Financial Tracking Service appeals, emergencies, and clusters collector. |
| [`hdxscraper-who`](hdxscraper-who/) | [WHO GHO](http://apps.who.int/gho/data/node.main.132?lang=en) | WHO Global Health Observatory data collector. |
| [`hdxscraper-world-bank-climate`](hdxscraper-world-bank-climate/) | [World Bank Climate Change Data](http://sdwebx.worldbank.org/climateportal/) | World Bank climate change data collector. |
| [`undp`](undp/) | [UNDP HDRO API](http://hdr.undp.org/en/data) | UNDP Human Development Report Office collector. |
| [`unhabitat`](unhabitat/) | [urbaninfo API](http://www.devinfo.org/urbaninfo/) | UN Habitat urbaninfo API collector. |
| [`migrant-deaths`](migrant-deaths/) | [IOM](https://www.iom.int/) | Scrapes the IOM migrant-casualty table. |
| [`un-casualty`](un-casualty/) | UN | Scrapes the UN casualty table. |

## Two styles of scraper

The scrapers fall into two groups.

### 1. `hdxscraper-*` (and `undp`, `unhabitat`) — Flask/SQLAlchemy apps

These are structured [ScraperWiki](https://scraperwiki.com/)-style apps built on Flask, Flask-SQLAlchemy, and [`manage.py`](https://github.com/reubano/manage.py). They share a common layout:

```
app/          # models.py, utils.py — data model and extraction logic
bin/          # setup, populate helper scripts
datasets/     # dataset metadata
tests/        # tests
config.py     # configuration
manage.py     # task runner
requirements.txt
```

**Setup**

> Use a [virtualenv](https://virtualenv.pypa.io/).

```sh
pip install -r requirements.txt
manage setup
manage init
```

**Run**

```sh
manage run
```

Results are written to a SQLite database (`scraperwiki.sqlite`). On a ScraperWiki Box, use `make setup` and `manage -m Scraper run`. See each scraper's own `README.md` for source-specific details.

### 2. `migrant-deaths`, `un-casualty` — standalone scripts

These are single-file scripts that scrape an HTML table with `requests` + `BeautifulSoup` and write a CSV.

```sh
pip install -r requirements.txt
./scrape data.csv
```

## Requirements

- Python 2.7 (the scrapers target the Python 2 era ScraperWiki platform)
- Per-scraper dependencies in each `requirements.txt`

## License

Each scraper is MIT licensed; see the `LICENSE` file within each directory.
