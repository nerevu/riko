---
source: ../../../../proposer/README.md
---

# proposer

![Image](../master/examples/company_super_awesome_project_proposal.png?raw=true)

## Introduction

Proposer is a [Flask](http://flask.pocoo.org) powered script that automatically
generates client proposals from
[yaml data files](http://en.wikipedia.org/wiki/YAML#Examples). Proposals can be output
as HTML, PDF (via [WeasyPrint](https://weasyprint.org/)), Markdown, or PNG. It has been
tested on the following configuration:

- MacOS X 10.7.5
- Python 2.7.5

## Requirements

Proposer requires the following in order to run properly:

- [Xcode](https://developer.apple.com/xcode)
- [Command Line Tools](http://jaranto.blogspot.com/2012/08/os-x-unable-to-execute-clang-no-such.html)
- [Python 2.7](http://www.python.org/download) (MacOS X comes with python preinstalled).
  Python 3 is not supported: the code imports `flask.ext.*` (Flask 0.10.1) and uses the
  Python 2 `file()` builtin.

## Quick Start

*Open Terminal*

	Applications > Terminal.app

*Clone repo (inside Terminal) - First time only*

	cd path/to/downloads
	git clone https://github.com/reubano/proposer.git

*Install python modules (inside Terminal) - First time only*

	cd path/to/downloads/proposer
	sudo easy_install pip
	sudo pip install -r requirements.txt

*Create proposals (inside Terminal) - Any time*

	cd path/to/downloads/proposer
	manage propose

The `manage` command comes from the `manage.py` package in `requirements.txt`;
`python manage.py propose` works as well.

## Scripts

Proposer comes with a built in script manager `manage.py`. Use it to create proposals.

### Usage

	manage [-m CFGMODE] [-f CFGFILE] propose [-h] [-s STYLE] [-i INFO] [-t OTYPE]

Options:

- `-s, --style` the proposal style/template (default: `development`). Available styles:
  `development`, `ccr`, `gun.io`, `hdx`. Each style reads a different set of data keys;
  see [Data file](#data-file).
- `-i, --info` the client info YAML file (default: `info.yml` in the proposer
  directory). A relative path is resolved from the current directory.
- `-t, --otype` the output type (default: `html`). One of: `html`, `pdf`, `md`, `png`.

Global options (they go before `propose`):

- `-m, --cfgmode` the configuration mode (default: `Development`). One of `Development`,
  `Production`, `Test`; see [Configuration](#configuration).
- `-f, --cfgfile` a Python settings file (intended; it has no effect today, see
  [Known issues](#known-issues)).

`manage` also has Flask-Script's built-in `runserver` and `shell` commands. With
`manage runserver`, `http://localhost:5000/<style>/` previews a proposal in the browser
and `/render/<style>/<otype>/` returns the rendered output; both read the data file set
by `INFO_PATH` (`info.yml` by default).

### Output

The generated proposal is written to the `exports/` directory of the proposer checkout
(not the current directory), as

	exports/<client>_<project>.<otype>

- `<client>` is `short_company_name`, or `client_name` when `short_company_name` is
  empty.
- `<project>` is `project_name`.
- The name is lowercased, with spaces replaced by `_`, `&` by `and`, and `/` by `-`.

For example, the default `info.yml` (`short_company_name: Company`,
`project_name: Super Awesome Project`) gives
`exports/company_super_awesome_project.html`. An existing file with the same name is
overwritten without a prompt.

What each output type contains:

- `html`: the rendered page with its stylesheets inlined and the jQuery and Bootstrap
  script tags removed, so the file stands alone.
- `md`: the rendered page converted to Markdown by `html2text`, wrapped at 65 columns,
  with emphasis removed.
- `pdf` and `png`: the page rendered by WeasyPrint.

The proposal is valid for `days_valid` days: the `development` style's terms section
shows today's date and an expiry date of today plus `days_valid`.

### Examples

The following examples assume you have first run `cd path/to/downloads/proposer`

*Use the default info.yml file*

	manage propose

*Use a custom template style (with the data file written for that style)*

	manage propose -s ccr -i ccr.yml

The `ccr` style reads keys such as `project_pain`, `project_goals`, `project_solution`,
and `options` that `info.yml` doesn't have, so pair it with `ccr.yml`.

*Generate a PDF instead of HTML*

	manage propose -t pdf

*Use a custom yaml file (you can drag and drop the file into the terminal instead of
typing in the path)*

	manage propose -i path/to/custom.yml

*Use production mode (minified Bootstrap and Font Awesome from a CDN)*

	manage -m Production propose

*Show the help menu*

	manage propose -h

## Configuration

Proposal content is defined in a YAML data file (default `info.yml`). The repo includes
the example data files `info.yml` (for the `development` style), `ccr.yml` (for the
`ccr` style), and `examples/example.yml` (an older `development` example). A
`client.yml` blank for the `ccr` style is intended as a starting point for new clients;
it isn't tracked in the repository today, so copy `ccr.yml` instead. The `sent/`
directory is a git-ignored place to archive the data files of proposals you have sent.

Your own contact and company details are set in `config.py`, and templates read them as
`site`:

Variable in `config.py` | Template key | Default
---|---|---
`__YOUR_NAME__` | `author` | `Reuben Cummings`
`__YOUR_COMPANY__` | `author_company` | `Nerevu Development`
`__YOUR_POSITION__` | `author_position` | `Managing Director`
`__YOUR_EMAIL__` | `author_email` | `rcummings@nerevu.com`
`__YOUR_SKYPE__` | `author_skype` | the `USER` (or `USERNAME`) environment variable
`__YOUR_PHONE__` | `author_phone` | a list of two phone numbers
`__YOUR_WEBSITE__` | `author_url` | `http://nerevu.com`
(computed) | `year`, `date` | today

### Modes

`-m/--cfgmode` picks a settings class from `config.py`. All modes share the defaults
`STYLE=development`, `TYPE=html`, `INFO_PATH=info.yml`, and `EXPORT_DIR=exports`.

Mode | Differences
---|---
`Development` (default) | `DEBUG` on; local, unminified Bootstrap assets
`Production` | minified Bootstrap and Font Awesome loaded from a CDN, which changes the asset links in the rendered output; `HOST` is `0.0.0.0` (the setting isn't read by the code)
`Test` | `TESTING` on

### Data file

Every top-level key of the data file becomes a template variable (`g.<key>`). Proposer
doesn't check the file against the style, so use the data file written for the style.

Keys every run needs:

Key | Why
---|---
`days_valid` | number of days the proposal is valid; every render computes the expiry date from it
`short_company_name` | output file name (may be empty, then `client_name` is used)
`client_name` | output file name when `short_company_name` is empty, and the client's name in the proposal
`project_name` | output file name, and the project title

Keys read by the templates of each style (`site` comes from `config.py`, not the data
file):

Style | Pairs with | Keys read
---|---|---
`development` | `info.yml`, `examples/example.yml` | the shared keys below, plus `client_position`, `days_valid`, `examples`, `hardware`, `hourly_rate`, `os`, `payment`, `platform`, `pricing` (`Fixed`, `Range`, or `Hourly`), `project_code`, `revision`, `schedule`, `technology`
`ccr` | `ccr.yml` | the shared keys below, plus `options`, `project_code`, `revision`
`gun.io` | (no example file) | the shared keys below
`hdx` | (no example file) | `apis`, `backend`, `client_address`, `client_contact_name`, `client_name`, `client_position`, `companies`, `features`, `frontend`, `full_company_name`, `languages`, `links`, `project_credits`, `project_estimate_ave`, `project_estimate_high`, `project_estimate_low`, `project_name`, `projects`, `short_company_name`, `timeframe`

Shared keys (read through the summary and skills sections and their macros, which
`development`, `ccr`, and `gun.io` all include): `client_contact_email`,
`client_contact_name`, `client_contact_phone`, `client_contact_skype`, `client_name`,
`currency`, `deliverables`, `experience`, `features`, `full_company_name`,
`include_contact_info`, `include_level_3`, `include_objectives`, `links`, `missing`,
`project_credits`, `project_estimate_ave`, `project_estimate_high`,
`project_estimate_low`, `project_goals`, `project_name`, `project_pain`,
`project_pain_image`, `project_solution`, `services`, `short_company_name`, `timeframe`.

Some keys in the example files aren't read by any template today: `client_email`,
`client_phone`, `license`, `project_goal` (the templates read `project_goals`),
`daily_rate` (`ccr.yml`), and `project_num` (`examples/example.yml`).

## Known issues

- `-f/--cfgfile` and the `APP_SETTINGS` environment variable have no effect through
  `manage`: `create_app` uses `config_mode` first, and `-m` always has a value
  (`manage.py:15-17`, `app/__init__.py:54-59`).
- `-s` and `-t` aren't validated. An unknown output type falls through without a
  response (`app/__init__.py:134-135`) and an unknown style has no template, so
  `propose` writes an error page or fails instead of a proposal.
- The `?source=` parameter of the `/render/<style>/` route uses the Python 2 `file()`
  builtin (`app/__init__.py:98`).
- A data file without `days_valid` fails every render (`app/__init__.py:70`). One
  without `short_company_name` or `project_name`, or with an empty `short_company_name`
  and no `client_name`, fails `propose` with a `KeyError` (`manage.py:44-45`).

## License

Proposer is distributed under the
[BSD License](http://opensource.org/licenses/BSD-3-Clause), the same as
[Flask](http://flask.pocoo.org) on which this program depends.
