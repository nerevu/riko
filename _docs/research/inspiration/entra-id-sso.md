---
source: ../../../../entra-id-sso/README.md
---

# Microsoft Entra ID SAML SSO Automation

PowerShell scripts for automating Microsoft Entra ID (Azure AD) configuration for
SAML-based SSO applications.

## Scripts

- **Configure-EntraIdSSO.ps1** - Initial SSO setup for an Entra ID **gallery**
  application. The defaults and the login-URL rule target Keeper Password Manager.
- **Renew-SamlCertificate.ps1** - Certificate renewal (certbot-style) for SAML-mode
  service principals in the tenant

## Overview

These scripts automate SAML 2.0 SSO configuration with Microsoft Entra ID (Azure AD).
They are designed to be:

- **Generic** - Works with any SAML SSO application (Keeper, Okta, etc.). Intended; see
  below.
- ✅ **Idempotent** - Safe to run multiple times (with limits; see
  [Re-running Configure](#re-running-configure))
- ✅ **Automated** - Minimal manual steps required
- **Flexible** - Configurable application names and identifiers. Display and gallery
  names are configurable; identifiers come from the service provider metadata.

As written, they are not generic SAML tooling:

- `Configure-EntraIdSSO.ps1` only creates applications from the Entra
  **application gallery**. It looks up the gallery template whose display name equals
  `-AppGalleryName` and instantiates it (`Configure-EntraIdSSO.ps1:574-584`). There is
  no non-gallery ("custom SAML app") path. If no template matches, the script fails.
- The application's sign-on URL is derived the Keeper way: the service provider's
  `entityID`, with `/saml/` replaced by `/ext_login/` (`:699`). For a service provider
  whose entity ID does not contain `/saml/`, the sign-on URL is the entity ID unchanged.
- The defaults (`-DisplayName "Keeper SSO"`,
  `-AppGalleryName "Keeper Password Manager"`, `-EnterpriseDomain "nerevu.com"`,
  `-notificationEmail "cif@nerevu.com"`) and the metadata auto-discovery
  (`keeper-metadata-<EnterpriseDomain>.xml`) are Keeper- and tenant-specific.
- `Renew-SamlCertificate.ps1` is not app-specific. It checks the SAML-mode service
  principals in the tenant.

Re-running is supported with limits; see [Re-running Configure](#re-running-configure).

### What the Scripts Automate

1. ✅ Finds the enterprise application by display name, or creates it from a gallery
   template
2. ✅ Configures SAML 2.0 single sign-on settings (identifier and reply URL from the
   service provider metadata)
3. ✅ Sets the Sign-on URL from the service provider entity ID (Keeper `/ext_login/`
   rule)
4. ✅ Configures user attributes and claims (optional and required claims, claims
   mapping policy)
5. ✅ Adds a SAML signing certificate when none exists or the newest one expires within
   `-RenewDays`
6. ✅ Configures user assignment settings and the notification email
7. ✅ Assigns **one** group (and, alongside it, one managed identity) to the application
8. ✅ Downloads Federation Metadata XML
9. ⚠️ Renews expiring SAML certificates. The renewal step is currently broken; see
   [Known issues](#known-issues).

## Prerequisites

### Before Running the Scripts

1. **Service Provider Configuration** (MUST be completed first):
   - Configure SSO in your service provider's admin console
   - Download the **Service Provider Metadata** XML file
   - Make sure the application exists in the Entra application gallery under the name
     you pass as `-AppGalleryName`

2. **Azure AD Permissions**:
   - Global Administrator OR Application Administrator role
   - Access to Azure Portal ([portal.azure.com](https://portal.azure.com) or
     [portal.azure.us](https://portal.azure.us) for Government)

3. **PowerShell Requirements**:
   - PowerShell 5.1 or PowerShell 7+
   - Microsoft Graph PowerShell modules:
     - `Configure-EntraIdSSO.ps1` installs any of these that are missing, for the
       current user: `Microsoft.Graph.Applications`,
       `Microsoft.Graph.Beta.Applications`, `Microsoft.Graph.Users`,
       `Microsoft.Graph.Groups`, `Microsoft.Graph.Authentication`,
       `Microsoft.Graph.Identity.SignIns`.
     - `Renew-SamlCertificate.ps1` installs nothing. It declares
       `#Requires -Modules Microsoft.Graph.Applications, Microsoft.Graph.Authentication`
       and will not start without them.
   - Internet connection

## Installation

1. Clone or download this repository
2. Ensure you have the Service Provider metadata XML file ready

## Usage

### Configure-EntraIdSSO.ps1

#### Basic Usage (Keeper Password Manager)

```powershell
.\Configure-EntraIdSSO.ps1 `
    -SPmetadataFile "C:\Path\To\keeper-metadata.xml" `
    -EnterpriseDomain "mycompany.com"
```

With every default, this finds or creates the enterprise app "Keeper SSO" from the
gallery template "Keeper Password Manager".

The sign-on URL (IdP-initiated login endpoint) is not a parameter. The script reads the
`entityID` from the metadata and replaces `/saml/` with `/ext_login/`
(`Configure-EntraIdSSO.ps1:699`), so a Keeper entity ID of
`https://keepersecurity.com/api/rest/sso/saml/<id>` becomes the sign-on URL
`https://keepersecurity.com/api/rest/sso/ext_login/<id>` automatically.

For non-Keeper apps the same rule applies:

- If the entity ID contains `/saml/`, that segment is replaced with `/ext_login/`, which
  is likely wrong for the app; correct the sign-on URL in the portal afterwards.
- If it does not, the sign-on URL is the entity ID unchanged; set the app's real login
  URL in the portal afterwards.
- If the metadata root element does not use the `md:` namespace prefix, no entity ID is
  found and the script silently skips the whole service principal update at `:730`:
  sign-on URL, SAML relay state, notification email, and the user-assignment
  requirement.

#### Automatic Metadata Discovery

If `-SPmetadataFile` is omitted, the script looks in `$env:OneDrive\Documents`, or else
`%USERPROFILE%\Documents`. It takes `keeper-metadata-<EnterpriseDomain>.xml` if present,
otherwise the first file matching `*metadata*.xml`. If nothing is found, the script
stops with "Failed to find … metadata file".

```powershell
# Uses Documents\keeper-metadata-mycompany.com.xml if it exists
.\Configure-EntraIdSSO.ps1 -EnterpriseDomain "mycompany.com"
```

`-EnterpriseDomain` is used only for this file name.

#### Another Gallery Application

```powershell
.\Configure-EntraIdSSO.ps1 `
    -SPmetadataFile "C:\Path\To\app-metadata.xml" `
    -AppGalleryName "Exact Gallery Template Name" `
    -DisplayName "My SSO Application" `
    -RelayState "https://app.example.com/"
```

The sign-on URL is still derived with the Keeper `/saml/` → `/ext_login/` rule; check it
in the portal afterwards.

#### Generic SSO Application (intended)

The intended use covers any SAML 2.0 application, configured from its metadata alone.
Configure only supports gallery-template apps today: as written, these examples fall
back to the default `-AppGalleryName "Keeper Password Manager"` template, and a name
with no matching template makes the script fail.

```powershell
.\Configure-EntraIdSSO.ps1 `
    -SPmetadataFile "C:\Path\To\app-metadata.xml" `
    -DisplayName "My SSO Application"
```

#### Generic SSO Application With User Assignment (intended)

```powershell
.\Configure-EntraIdSSO.ps1 `
    -SPmetadataFile ".\app-metadata.xml" `
    -DisplayName "My SSO App" `
    -UserAssignmentRequired $true `
    -AssignedGroup "IT Security Group"
```

`-AssignedGroup` takes one group; individual users are not assigned.

#### With Claims and Group Assignment

```powershell
.\Configure-EntraIdSSO.ps1 `
    -SPmetadataFile ".\keeper-metadata.xml" `
    -EnterpriseDomain "mycompany.com" `
    -AssignedGroup "Staff" `
    -RequiredClaims "streetaddress", "postalcode", "country"
```

`-RequiredClaims` currently hits a script defect when the claims policy does not exist
yet; see [Known issues](#known-issues).

#### For Azure Government Cloud

```powershell
.\Configure-EntraIdSSO.ps1 `
    -SPmetadataFile ".\app-metadata.xml" `
    -GovernmentCloud
```

In Configure, `-GovernmentCloud` only switches the federation-metadata download host to
`login.microsoftonline.us` and the portal links to `portal.azure.us`. The Graph sign-in
itself does not pass a government environment (`Connect-MgGraph -Scopes` at `:388`).

#### Re-running Configure

```powershell
# First run - creates the app (no prompt)
.\Configure-EntraIdSSO.ps1 -SPmetadataFile "keeper.xml" -AssignedGroup "Staff"

# Later runs - reconfigure the existing app without the y/N prompt
.\Configure-EntraIdSSO.ps1 -SPmetadataFile "keeper.xml" -AssignedGroup "Staff" -Force
```

On a later run, the app is found by `-DisplayName`. Without `-Force`, the script asks
"Do you want to reconfigure the existing service principal? (y/N)" and exits 0 on
anything but `y`. When it continues:

| Step | On re-run |
| --- | --- |
| SAML mode, identifier URI, reply URL, sign-on URL, notification email, relay state | overwritten |
| Claims mapping policy `"<DisplayName> Claims Policy"` | updated if it exists, else created; then re-assigned to the service principal |
| Signing certificate | added only if none exists or the newest expires within `-RenewDays` |
| `-AssignedGroup` | skipped if the group already has an assignment |
| `-AssignedMSI` app roles | appended to the current app roles with no duplicate check (`:720`) |

There is no dry-run or `WhatIf` mode in Configure.

### Renew-SamlCertificate.ps1

#### Basic Certificate Renewal

```powershell
# Check all SAML apps and renew expiring certificates
.\Renew-SamlCertificate.ps1

# Test mode - see what would be renewed
.\Renew-SamlCertificate.ps1 -DryRun

# Renew certificates expiring within 45 days
.\Renew-SamlCertificate.ps1 -RenewDays 45

# Quiet mode for scheduled tasks
.\Renew-SamlCertificate.ps1 -Quiet
```

#### Application-Specific Renewal

```powershell
# Renew only a specific application's certificate
.\Renew-SamlCertificate.ps1 -ApplicationName "My SSO Application"

# Force renewal even if not expiring
.\Renew-SamlCertificate.ps1 -ApplicationName "My SSO Application" -Force
```

#### Renewal rules

For each service principal with `PreferredSingleSignOnMode` `saml` (an exact
`displayName` match when `-ApplicationName` is given). The listing is not paged:
`Get-MgServicePrincipal` is called without `-All` (`Renew-SamlCertificate.ps1:227`), so
only the first page of service principals is examined.

1. Take the newest `Sign` key credential by `EndDateTime`. Older signing certificates
   are ignored.
2. `DaysUntilExpiration` is the whole number of days until that certificate's end date.
3. Renew if `-Force` is set; else if the certificate has expired (`DaysUntilExpiration`
   < 0); else if `DaysUntilExpiration -le RenewDays`.
4. To renew, add a token-signing certificate named `Auto-renewed <yyyy-MM-dd>`, valid
   for one year. Then set it as the preferred signing certificate, set
   `notificationEmailAddresses` if `-NotifyEmail` was given, and download the new
   federation metadata.

With `-DryRun`, the script logs what it would do, counts each candidate as "renewed",
and makes no Graph changes and no metadata files; the log file is still written.
`-DryRun` is the only preview: the script declares `SupportsShouldProcess`, so `-WhatIf`
is accepted, but it never calls `ShouldProcess`.

#### Scheduling Automatic Renewals

**Windows Task Scheduler:**

```powershell
# Create a scheduled task to run weekly
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-File C:\Scripts\Renew-SamlCertificate.ps1 -Quiet"

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 2am

Register-ScheduledTask -TaskName "SAML Certificate Renewal" `
    -Action $action -Trigger $trigger -Description "Automatic SAML certificate renewal"
```

**Linux/macOS cron:**

```bash
# Add to crontab - runs every Sunday at 2 AM
0 2 * * 0 /usr/local/bin/pwsh /path/to/Renew-SamlCertificate.ps1 -Quiet
```

Scheduled runs need a Graph sign-in. The script calls `Connect-MgGraph -Scopes`
interactively and has no app-only (certificate or secret) option.

## Parameters

### Configure-EntraIdSSO.ps1

| Parameter | Required | Type | Description | Default |
|-----------|----------|------|-------------|---------|
| `SPmetadataFile` | No | string | Path to the service provider metadata XML | auto-discovered (see above) |
| `EnterpriseDomain` | No | string | Only used in the auto-discovered file name `keeper-metadata-<EnterpriseDomain>.xml` | `"nerevu.com"` |
| `DisplayName` | No | string | Enterprise app (service principal) display name to find or create; also names the claims policy and the certificate | `"Keeper SSO"` |
| `AppGalleryName` | No | string | Exact display name of the gallery template to instantiate | `"Keeper Password Manager"` |
| `Mode` | No | `saml` \| `notSupported` \| `oidc` | Written to `preferredSingleSignOnMode`. The remaining steps are SAML steps whatever the mode. | `"saml"` |
| `notificationEmail` | No | string | Certificate notification address (`notificationEmailAddresses`) | `"cif@nerevu.com"` |
| `RenewDays` | No | int, 1-365 | Add a signing certificate if the newest expires within this many days | `30` |
| `OutputDirectory` | No | string | Where the log and federation metadata go. A missing or nonexistent path falls back to the Documents folder (OneDrive, then profile), then `.` | Documents folder |
| `UserAssignmentRequired` | No | bool | `appRoleAssignmentRequired`; pass `-UserAssignmentRequired $false` to turn off | `$true` |
| `AssignedGroup` | No | string | Display name of **one** group to assign | none |
| `AssignedMSI` | No | string | Display name of **one** managed identity whose application app roles are added; its assignment runs only when `-AssignedGroup` is also given | none |
| `RequiredClaims` | No | string[] from `givenname, surname, streetaddress, postalcode, country, mobilephone, employeeid` | Claims added through a claims mapping policy, each as `http://schemas.xmlsoap.org/ws/2005/05/identity/claims/<name>` | none |
| `OptionalClaims` | No | string[] from a fixed list of user attributes (`mail`, `userprincipalname`, `department`, `jobtitle`, …) | Added as non-essential `saml2Token` optional claims on the application | none |
| `RelayState` | No | string | SAML relay state | none |
| `AddBasicClaims` | No | switch | Sets `IncludeBasicClaimSet` in the claims mapping policy (creates the policy even with no required claims) | off |
| `GovernmentCloud` | No | switch | Government metadata host and portal links (see above) | off |
| `Force` | No | switch | Skip the reconfigure prompt for an existing app | off |

### Renew-SamlCertificate.ps1

| Parameter | Description | Default |
|-----------|-------------|---------|
| `-RenewDays` | Days before expiration to trigger renewal (1-365) | 30 |
| `-ApplicationName` | Exact display name of one application | All SAML apps |
| `-OutputDirectory` | Where the log and the `Renewal-*` metadata folders go | `.` |
| `-DryRun` | Test mode - no changes made | False |
| `-Force` | Renew even if not expiring | False |
| `-Quiet` | Hide `Info` and `Debug` messages on the console (the log file keeps everything); also disconnects from Graph at the end | False |
| `-GovernmentCloud` | Connect with `-Environment USGov` and download metadata from `login.microsoftonline.us` | False |
| `-NotifyEmail` | Address written to the app's `notificationEmailAddresses` on renewal. The script sends no email itself. | none |

## Output

### Configure-EntraIdSSO.ps1

Creates in `OutputDirectory`:

1. **Log File**: `EntraIdSSO-Setup-YYYYMMDD-HHMMSS.log`
2. **Federation Metadata**: `azure-federation-metadata-YYYYMMDD-HHMMSS.xml`

**Exit Codes:**

- `0`: Configuration completed and metadata downloaded, or the user declined the
  reconfigure prompt
- `1`: Any failure

### Renew-SamlCertificate.ps1

Creates in `OutputDirectory`:

1. **Log File**: `SamlCertRenewal-YYYYMMDD-HHMMSS.log`
2. **Metadata Files**: `Renewal-YYYYMMDD-HHMMSS\azure-federation-metadata.xml` per
   renewed application

**Exit Codes** (as assigned in the code):

- `0`: The run reached the end without (renewals > 0 and failures > 0). This includes
  "no SAML applications found", "no renewal needed", dry runs, and runs where **every**
  renewal failed.
- `1`: Graph sign-in failed, or an exception was caught by the top-level handler
- `2`: At least one renewal succeeded and at least one failed

Intended codes the code never returns (also listed in the script's help block):

- `3`: Authentication failed (actually returns `1`)
- `4`: No applications found (actually returns `0`)

`1` was intended to mean "No certificates needed renewal"; the code returns `0` in that
case. Because of the issues listed under [Known issues](#known-issues), a non-dry
renewal currently always fails, and the summary step raises before the exit code is set.

## Manual Steps Still Required

After running **Configure-EntraIdSSO.ps1**, the script prints these steps with direct
portal links:

1. **Edit Claims** (claims configuration page):
   - Remove unused claims as required ()
   - Add additional claims as required

2. **Upload Service Provider Metadata to Azure** (Single sign-on page):
   - Click the 'Upload metadata file' button
   - Upload the service provider metadata file used for the run

3. **Upload Azure Metadata to Service Provider**:
   - Open your service provider's admin console
   - Navigate to SSO/SAML configuration
   - Select "Azure AD" or "Entra ID" as Identity Provider
   - Upload the downloaded `azure-federation-metadata-*.xml` file

4. **Test SSO Connection**:
   - Assign a test user
   - Have them login via SSO
   - Verify authentication works

5. **Set Certificate Renewal Reminder**:
   - Azure AD SAML certificates expire after 1 year
   - Set a calendar reminder for 11 months from now
   - OR schedule Renew-SamlCertificate.ps1 to run automatically

Also check after Configure (the script does not print this step):

- **Verify Azure Portal Configuration**:
  - Check User Attributes & Claims section
  - Delete any unnecessary additional claims
  - Verify Email claim uses correct attribute

After running **Renew-SamlCertificate.ps1**, you must:

1. **Upload New Metadata** to your service provider's admin console
2. **Test SSO** - Verify users can authenticate
3. **Monitor Logs** - Check the generated log files for any issues

## Troubleshooting

### Permission Issues

```powershell
# Run PowerShell as Administrator
# Reconnect with the scopes Configure-EntraIdSSO.ps1 requests
Connect-MgGraph -Scopes "Application.ReadWrite.All","AppRoleAssignment.ReadWrite.All","Directory.AccessAsUser.All","Directory.ReadWrite.All","Group.Read.All","Policy.ReadWrite.ApplicationConfiguration","Policy.Read.All","User.Read.All"
```

If the current session already has these scopes, Configure reuses it.
`Renew-SamlCertificate.ps1` always connects with `Application.ReadWrite.All` and
`Directory.Read.All`. Configure disconnects from Graph when it finishes.

### Module Installation Issues

```powershell
# Install manually with elevated privileges
Install-Module Microsoft.Graph -Scope AllUsers -Force
```

### Certificate Not Generated

If the script completes but no certificate appears in Azure:

1. Wait 2-5 minutes
2. Refresh the Azure portal page
3. Navigate to: Enterprise Applications > Your App > Single sign-on > SAML Signing
   Certificate

### User Assignment Issues

If users can't login:

1. Check that users are assigned to the application
2. Verify "User assignment required" setting matches your needs
3. Ensure users exist in Azure AD

## Important Notes

### Certificate Expiration

⚠️ **IMPORTANT**: Configure and Renew create SAML signing certificates valid for 1 year.

**Options:**

- Set a calendar reminder to manually renew 11 months from now
- Schedule `Renew-SamlCertificate.ps1`. Until the renewal defect in
  [Known issues](#known-issues) is fixed, check its log rather than relying on it.

### User Principal Name vs Email

If your `user.userprincipalname` (UPN) differs from the user's actual email address:

1. Go to Azure Portal > Enterprise Applications > Your App > Single sign-on
2. Edit the Email claim
3. Change from `user.userprincipalname` to `user.mail`

## Supported Applications

`Configure-EntraIdSSO.ps1` supports applications that:

- exist in the Entra application gallery under the exact name passed as
  `-AppGalleryName`;
- publish SP metadata whose root element uses the `md:` namespace prefix. The script
  queries `//md:EntityDescriptor` and `//md:AssertionConsumerService` with the root
  element's own prefix (`:450-453`, `:641-642`);
- accept a sign-on URL built from the entity ID with `/saml/` replaced by `/ext_login/`
  (Keeper's IdP-initiated login endpoint), or can have it corrected by hand afterwards.

It is written and defaulted for **Keeper Password Manager**. Other gallery apps can be
targeted with `-AppGalleryName`/`-DisplayName`, with the sign-on URL caveat above.
Non-gallery (custom) SAML applications are not supported.

`Renew-SamlCertificate.ps1` works on SAML-mode service principals in the tenant (first
page only; see Renewal rules).

The intended scope is broader than the code supports today:

> This script works with **any SAML 2.0 compatible SSO application**, including:
>
> - Keeper Password Manager
> - Okta
> - OneLogin
> - Auth0
> - Custom SAML applications
> - Any service provider that uses SAML 2.0 authentication
>
> Simply provide the appropriate:
>
> - Service Provider metadata XML file
> - IdP Initiated Login Endpoint
> - Application display name and identifier

## Other files

- `test.ps1` - a scratch walk-through of the Graph SAML setup calls for an AWS IAM
  Identity Center gallery app. It is not used by either script.
- `Keeper SSO(Microsoft Graph format).json` - a Graph export of a configured "Keeper
  SSO" application, for reference.
- `IDEMPOTENCY-ANALYSIS.md` - an analysis of the earlier
  `Configure-KeeperSSOAzureAD.ps1` script, not the current one.
- `Keeper Entra ID (Azure AD).md` / `.pdf` - Keeper's own Entra ID setup guide.

## Version History

- **2.0** (2025-11-06): Renamed and partly generalized
  - Added the `DisplayName` and `AppGalleryName` parameters. The defaults, the metadata
    auto-discovery, and the sign-on URL rule are still Keeper-specific.
  - Simplified logging (removed centralized module)
  - Renamed scripts: Configure-EntraIdSSO.ps1, Renew-SamlCertificate.ps1
  - Updated all documentation

- **1.3** (2025-11-06): Centralized logging module
  - Added KeeperLogging.psm1 for consistent logging
  - Both scripts use centralized logging with fallback

- **1.2** (2025-11-06): Idempotency improvements
  - Added -Force parameter
  - Made group assignment idempotent
  - Safe to re-run for configuration updates

- **1.1** (2025-11-06): Certificate renewal feature
  - Added Update-KeeperSAMLCertificate.ps1
  - Certbot-style automatic renewal
  - Schedulable via Task Scheduler or cron

- **1.0** (2025-11-06): Initial Keeper-specific release
  - Automated Azure AD configuration
  - SAML 2.0 setup
  - User and group assignment

## Known issues

- Renewal never adds a certificate. `$servicePrincipalId` is never assigned in
  `Renew-SamlCertificate.ps1`, yet it is passed to
  `Add-MgServicePrincipalTokenSigningCertificate` (`:341`) and
  `Update-MgServicePrincipal` (`:604`). The certificate call's error is caught (`:352`),
  so the app counts as a failed renewal. Because no renewal succeeds, the exit-code rule
  returns 0, not 2 (`:624-628`).
- The renewal summary raises before the exit code is set. `Write-RenewalSummary` opens
  with ``Write-Log "`n" -NoNewline`` (`Renew-SamlCertificate.ps1:454`), but `Write-Log`
  declares no `-NoNewline` parameter (`:151-156`). The error lands in the top-level
  `catch` (`:634`), so a run that reaches the summary exits with the initial value 1.
- `-WhatIf` is accepted by `Renew-SamlCertificate.ps1` (`SupportsShouldProcess`, `:102`)
  but the script never calls `ShouldProcess`, so it does not prevent changes. Use
  `-DryRun`.
- The "No SAML certificates found for this application" branch
  (`Renew-SamlCertificate.ps1:577-580`) cannot run, because `Get-CertificateInfo` always
  returns an object (`:269`).
- The help block's exit codes 3 and 4 (`Renew-SamlCertificate.ps1:88-92`) are never
  returned, and `-NotifyEmail`'s help (`:43-45`) mentions SMTP/SendGrid, which the
  script does not use.
- Creating the claims mapping policy drops arguments. `Configure-EntraIdSSO.ps1:844` has
  no line-continuation backtick after `-IsOrganizationDefault $false`.
  `New-MgPolicyClaimMappingPolicy` therefore receives neither `-DisplayName` nor
  `-ErrorVariable`, and `:845-846` run as a separate statement. This path runs whenever
  `-RequiredClaims` or `-AddBasicClaims` is given and no `"<DisplayName> Claims Policy"`
  exists yet.
- The `-AssignedMSI` role assignment passes no assignment body. `$roleAssignment` is
  built (`Configure-EntraIdSSO.ps1:1105-1111`), but
  `New-MgServicePrincipalAppRoleAssignment` is called with only `-ServicePrincipalId`
  (`:1115`). The step also runs only when `-AssignedGroup` is set (`:1321-1323`).
- When `-AssignedGroup` is not found, the error message prints an empty name, because it
  uses `$Group` (`Configure-EntraIdSSO.ps1:1046`).
- `Connect-ToGraph` passes `"2.32.0"` as a module name to `Install-Prerequisites`,
  because the version pair is flattened into its `[string[]]` parameter
  (`Configure-EntraIdSSO.ps1:334-335`, `:470`). The result is ignored.

## License

This script is provided as-is for use with SAML SSO applications.

## Contributing

Feel free to submit issues or pull requests for improvements.

---

**Generated for Microsoft Entra ID SAML SSO Automation**
