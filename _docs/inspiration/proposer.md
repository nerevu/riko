# proposer

![Image](../master/examples/company_super_awesome_project_proposal.png?raw=true)

## Introduction

Proposer is a [Flask](http://flask.pocoo.org) powered script that automatically generates client proposals from [yaml data files](http://en.wikipedia.org/wiki/YAML#Examples). Proposals can be output as HTML, PDF (via [WeasyPrint](https://weasyprint.org/)), Markdown, or PNG. It has been tested on the following configuration:

- MacOS X 10.7.5
- Python 2.7.5

## Requirements

Proposer requires the following in order to run properly:

- [Xcode](https://developer.apple.com/xcode)
- [Command Line Tools](http://jaranto.blogspot.com/2012/08/os-x-unable-to-execute-clang-no-such.html)
- [Python >= 2.7](http://www.python.org/download) (MacOS X comes with python preinstalled)

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

## Scripts

Proposer comes with a built in script manager `manage.py`. Use it to create proposals.

### Usage

	manage propose [-h] [-s STYLE] [-i INFO] [-t OTYPE]

Options:

- `-s, --style` the proposal style/template (default: `development`). Available styles: `development`, `ccr`, `gun.io`, `hdx`.
- `-i, --info` the client info YAML file (default: `info.yml`)
- `-t, --otype` the output type (default: `html`). One of: `html`, `pdf`, `md`, `png`.

The generated proposal is written to the `exports/` directory.

### Examples

The following examples assume you have first run `cd path/to/downloads/proposer`

*Use the default info.yml file*

	manage propose

*Use a custom template style*

	manage propose -s ccr

*Generate a PDF instead of HTML*

	manage propose -t pdf

*Use a custom yaml file (you can drag and drop the file into the terminal instead of typing in the path)*

	manage propose -i path/to/custom.yml

*Show the help menu*

	manage propose -h

## Configuration

Proposal content is defined in a YAML data file (default `info.yml`); the repo includes
example data files such as `info.yml`, `client.yml`, and `ccr.yml`. Your own contact and
company details (author name, company, email, phone, website) are set in `config.py`.

## License

Proposer is distributed under the [BSD License](http://opensource.org/licenses/BSD-3-Clause), the same as [Flask](http://flask.pocoo.org) on which this program depends.
