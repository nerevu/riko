---
source: ../../../../contacts/README.md
---

# Contacts

A working folder for consolidating personal contacts exported from several sources
(Google Contacts, LinkedIn, and the Capsule CRM), plus a small Google People API
script for pulling contacts programmatically.

## Contents

### Script

| File | Description |
| ---- | ----------- |
| `quickstart.py` | Google [People API][people] quickstart. Authenticates via OAuth2 and prints the display names of the first few connections. |

[people]: https://developers.google.com/people

### Exported data

The exports don't share an encoding or a line ending, so each file needs its own
reader settings.

| File | Source / format | Encoding | Line endings | Size |
| ---- | --------------- | -------- | ------------ | ---- |
| `contacts.csv` | Outlook-style CSV export (full field set: name, emails, phones, addresses, etc.) | UTF-8 | CR (classic Mac) | 2137 rows × 88 columns |
| `google_contacts.csv` | Google Contacts export in Outlook CSV format | UTF-8 | CR (classic Mac) | 2137 rows × 62 columns |
| `google.csv` | Google Contacts export in Google CSV format | UTF-16LE with BOM | CRLF | 2137 rows × 135 columns |
| `capsule_contacts.vcf` | vCard 3.0 export from Capsule CRM | UTF-8 | LF | 177 cards |
| `linkedin_connections.vcf` / `linkedin_connections_export.vcf` | vCard 2.1 exports of LinkedIn connections. The two files are different exports, not copies (they first differ at line 2219). | Mac OS Roman, not UTF-8; no `CHARSET` parameter (e.g. byte `0xD0` is an en dash, `0x8E` is `é`) | CRLF | 1141 / 1135 cards |
| `conacts.html` | HTML fragment (no `<html>` wrapper) of CRM relationship cards. A `#contacts` div holds four groups in this order: `referrers`, `contractors`, `competitors`, `clients`. Each card has a stage-indicator class (`potential`, `noqual`, `inactive` or `current`), a headline and, on most cards, a subline (145 of 175) and a "reason" line (154 of 175) such as `3 years ago (mail from you)`. | UTF-8 | LF | 175 cards (141 potential, 15 noqual, 10 inactive, 9 current) |
| `Contacts_Import.csv` | Sample import template (HubSpot-style: Email, First/Last Name, Phone, Address, Lifecycle Stage) | ASCII | CR (classic Mac) | 1 row × 8 columns |
| `linkedin_test.csv` | Small sample CSV (First/Last Name, E-mail, Company, Job Title) | ASCII | CR (classic Mac) | 3 rows × 5 columns |

Row counts exclude the header row.

## `quickstart.py`

Fetches your Google contacts ("connections") via the People API.

### Requirements

- Python
- `google-api-python-client`, `oauth2client`, `httplib2`

```bash
pip install google-api-python-client oauth2client httplib2
```

### Setup

1. Enable the People API in the [Google Cloud Console][console] and create OAuth
   client credentials.
2. Download the credentials as `client_secret.json` and place it in your home
   directory (`~/client_secret.json`).
3. Create the token directory, `~/.credentials`, if it doesn't exist (the script
   fails without it, see [Known issues](#known-issues)).
4. Run the script. On first run it opens a browser to authorize read-only access to
   your contacts; the resulting token is cached at
   `~/.credentials/people.googleapis.com-python-quickstart.json`.

```bash
mkdir -p ~/.credentials
python quickstart.py
```

The script requests the `contacts.readonly` scope and prints the display names of the
first 5 connections. If you change the scope, delete the cached token so the next run
asks for authorization again.

[console]: https://console.cloud.google.com/

## Notes

- These CSV/VCF files contain personal contact information — keep them out of version
  control and avoid sharing publicly.
- `conacts.html` is a typo of "contacts" in the original filename, preserved as-is.

## Known issues

- `quickstart.py` calls `os.makedirs` to create `~/.credentials` but never imports
  `os` (it only imports `from os import path as p`), so on a machine without that
  directory the first run raises `NameError` before the OAuth flow starts
  (`quickstart.py:1`, `quickstart.py:31-32`).
