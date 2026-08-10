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

| File | Source / format |
| ---- | --------------- |
| `contacts.csv` | Outlook-style CSV export (full field set: name, emails, phones, addresses, etc.) |
| `google_contacts.csv` | Google Contacts export in Outlook CSV format |
| `google.csv` | Google Contacts export in Google CSV format (UTF-16) |
| `capsule_contacts.vcf` | vCard export from Capsule CRM |
| `linkedin_connections.vcf` / `linkedin_connections_export.vcf` | vCard exports of LinkedIn connections |
| `conacts.html` | Rendered HTML view of contacts |
| `Contacts_Import.csv` | Sample import template (HubSpot-style: Email, First/Last Name, Phone, Address, Lifecycle Stage) |
| `linkedin_test.csv` | Small sample CSV (First/Last Name, E-mail, Company, Job Title) |

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
3. Run the script. On first run it opens a browser to authorize read-only access to
   your contacts; the resulting token is cached at
   `~/.credentials/people.googleapis.com-python-quickstart.json`.

```bash
python quickstart.py
```

The script requests the `contacts.readonly` scope and prints the display names of the
first 5 connections.

[console]: https://console.cloud.google.com/

## Notes

- These CSV/VCF files contain personal contact information — keep them out of version
  control and avoid sharing publicly.
- `conacts.html` is a typo of "contacts" in the original filename, preserved as-is.
