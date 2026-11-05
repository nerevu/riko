---
source: ../../../../csv2html/README.md
---

# csv2html

Converts CSV files into styled HTML tables. `csv2html` reads a CSV, renders it as a
Markdown table, and exports it as an HTML page using GitHub-style CSS (approach adapted
from [GRIP](https://github.com/joeyespo/grip)). Serving the page over HTTP is intended
(not implemented); today the page is only written to a file.

- **Version:** 0.5.3
- **License:** MIT
- **Author:** Reuben Cummings

> **Note:** This is a legacy Python 2 project (uses `print` statements and
> `flask.ext.script`). It targets Flask 0.10 / Jinja2 2.7 era dependencies.

## How it works

`csv2html` builds a small Flask app whose index route renders the converted CSV, and
renders that route in-process through Flask's test client (`app.test_client()`). No
server is started and nothing listens on a port. The CLI reads the CSV, builds a
Markdown table with [`tabulate`][tabulate], hands it to the Flask app, and writes the
rendered HTML to a file.

The GitHub styles are inlined into the page in a `<style>` block, so the HTML file is
self-contained. They come from the CSS files cached in the package's `csv2html/static/`
directory (`github.css` and `github2.css` ship with it). Only when that directory holds
no `.css` file does `csv2html` fetch the stylesheet links from
<https://github.com/joeyespo/grip>, download them into `csv2html/static/`, and use them
from then on.

[tabulate]: https://pypi.org/project/tabulate/

> The bundled `run` command's column mapping is currently specialized for an eBay/Amazon
> LEGO price-scraper CSV (it expects `ebay_img_url`, `ebay_title`, `ebay_url`,
> `ebay_end_date`, `ebay_end_time`, `ebay_price_and_shipping` columns). Adjust
> `csv2html/main.py` to map your own CSV columns.

### Output

| Column | Built from |
| ------ | ---------- |
| `Image` | `<img src="ebay_img_url">` (shown 150px wide) |
| `Title` | `[ebay_title](ebay_url)`, a link |
| `End Date` | `ebay_end_date, ebay_end_time` |
| `Price (GBP)` | `ebay_price_and_shipping` |

- The column headers are fixed; they don't come from the CSV.
- The page title is the HTML file's basename without its extension, capitalized, plus
  a space and `results` (`-F lego.html` gives `Lego results`).
- The CSV is read, and the HTML written, as `utf-8-sig`, so the HTML file starts with a
  UTF-8 byte-order mark.

## Installation

```bash
pip install -r requirements.txt
python setup.py install   # installs the `csv2html` script
```

## Usage

```bash
csv2html [-m MODE] run [options]
```

`csv2html` is a Flask-Script manager with a single command, `run`. The conversion
options belong to `run`; `-m` is a manager option and goes before `run`.

### Options

| Option | Given | Description | Default |
| ------ | ----- | ----------- | ------- |
| `-f, --csv-file` | after `run` | CSV file to import | `~/unparsed.csv` |
| `-F, --html-file` | after `run` | HTML file to export | `~/unparsed.html` |
| `-m, --cfgmode` | before `run` | Config mode (from `csv2html/config.py`) | `Development` |
| `-V, --version` | after `run` | Display version and exit | |

`Development` sets Flask's `DEBUG` and prints a full traceback when the styles can't be
fetched; `Production` prints a one-line error instead (csv2html/config.py).

`run` exits 0 on success. On any error it writes `ERROR: <message>` to stderr, prints
the traceback, and exits 1.

### Examples

```bash
# Convert a specific CSV to HTML
csv2html run -f data.csv -F data.html

# Use the Production config mode
csv2html -m Production run -f data.csv -F data.html

# Show version
csv2html run -V

# Show help
csv2html -h
csv2html run -h
```

You can also run the entry point directly from a checkout during development:

```bash
python bin/csv2html run
```

## Development

`bin/csv2html` is the entry point. `manage.py` is a separate Flask-Script manager for
development tasks, run as `python manage.py <command>`:

| Command | Description |
| ------- | ----------- |
| `lint` | Check style with flake8 |
| `testnose` | Run nosetests |
| `test [-w]` | Run nosetests, then the script tests (`tests/testscript-*.py`) and the binary tests (`tests/testdist-*.py`); `-w` for Windows |
| `testall` | Run `test` for Windows, then for Mac |
| `require` | Regenerate `requirements.txt` from `pip freeze` |
| `install [-w]` | Build an sdist and pip-install it (Windows: via `pywinmk`) |
| `build [-w]` | `install`, then build a single-file PyInstaller binary (Mac: into `dist/<platform>`) |
| `buildall` | `build` for Windows, then for Mac |
| `checkstage` | Check staged changes (pre-commit hook) |

The PyInstaller build uses the hooks in `hooks/` and bundles the CSS and templates. The
Mac build looks for packages in `~/.virtualenvs/csv2html/lib/python2.7/site-packages`,
and the Windows build expects `../pywinmk/pywinmk.sh` under Wine.

## Project layout

| Path | Description |
| ---- | ----------- |
| `bin/csv2html` | Executable entry point |
| `csv2html/__init__.py` | Flask app factory + style caching |
| `csv2html/main.py` | CLI (Flask-Script `Manager`) and CSV → Markdown logic |
| `csv2html/renderer.py` | Markdown → HTML rendering |
| `csv2html/templates/` | Jinja HTML template |
| `csv2html/static/` | Bundled CSS |
| `manage.py` | Development, test, and PyInstaller build commands |
| `hooks/` | PyInstaller hooks |
| `tests/` | Test suite: scripttest scripts for the native script and the built binaries |

## Known issues

- `csv2html -f data.csv` (options without `run`) fails, because the manager has no
  default command (csv2html/main.py:19, 46-55).
- `python manage.py checkstage` runs `csv2html/tests/test.sh`, which doesn't exist
  (manage.py:107-112).
- When the style cache is empty, the fetched CSS is written into the installed package's
  `static/` directory (`csv2html/__init__.py:83-98`, `137-144`). If that directory isn't
  writable, or the fetch fails, the error is printed and the page is written without the
  GitHub styles (`csv2html/__init__.py:101-106`).

## License

MIT — see [LICENSE](LICENSE).
