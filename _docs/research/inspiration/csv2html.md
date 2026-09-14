# csv2html

Converts CSV files into styled HTML tables. `csv2html` reads a CSV, renders it as a
Markdown table, and serves/exports it as an HTML page using GitHub-style CSS (approach
adapted from [GRIP](https://github.com/joeyespo/grip)).

- **Version:** 0.5.3
- **License:** MIT
- **Author:** Reuben Cummings

> **Note:** This is a legacy Python 2 project (uses `print` statements and
> `flask.ext.script`). It targets Flask 0.10 / Jinja2 2.7 era dependencies.

## How it works

`csv2html` spins up a small Flask app whose index route renders the converted CSV.
The CLI reads the CSV, builds a Markdown table with [`tabulate`][tabulate], hands it to
the Flask app, and writes the rendered HTML (with cached GitHub styles) to a file.

[tabulate]: https://pypi.org/project/tabulate/

> The bundled `run` command's column mapping is currently specialized for an eBay/Amazon
> LEGO price-scraper CSV (it expects `ebay_img_url`, `ebay_title`, `ebay_url`,
> `ebay_end_date`, `ebay_end_time`, `ebay_price_and_shipping` columns). Adjust
> `csv2html/main.py` to map your own CSV columns.

## Installation

```bash
pip install -r requirements.txt
python setup.py install   # installs the `csv2html` script
```

## Usage

```bash
csv2html [options]
```

### Options

| Option | Description | Default |
| ------ | ----------- | ------- |
| `-f, --csv-file` | CSV file to import | `~/unparsed.csv` |
| `-F, --html-file` | HTML file to export | `~/unparsed.html` |
| `-m, --cfgmode` | Config mode (from `csv2html/config.py`) | `Development` |
| `-V, --version` | Display version and exit | |

### Examples

```bash
# Convert a specific CSV to HTML
csv2html -f data.csv -F data.html

# Show version
csv2html -V

# Show help
csv2html -h
```

You can also invoke it via the management script during development:

```bash
python bin/csv2html
```

## Project layout

| Path | Description |
| ---- | ----------- |
| `bin/csv2html` | Executable entry point |
| `csv2html/__init__.py` | Flask app factory + style caching |
| `csv2html/main.py` | CLI (Flask-Script `Manager`) and CSV → Markdown logic |
| `csv2html/renderer.py` | Markdown → HTML rendering |
| `csv2html/templates/` | Jinja HTML template |
| `csv2html/static/` | Bundled CSS |
| `tests/` | Test suite |

## License

MIT — see [LICENSE](LICENSE).
