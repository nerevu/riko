# Microsoft Entra ID SAML SSO Automation

PowerShell scripts for automating Microsoft Entra ID (Azure AD) configuration for SAML-based SSO applications.

## Scripts

- **Configure-EntraIdSSO.ps1** - Initial SSO setup and configuration for any SAML application
- **Renew-SamlCertificate.ps1** - Automatic certificate renewal (certbot-style)

## Overview

These scripts automate SAML 2.0 SSO configuration with Microsoft Entra ID (Azure AD), supporting any SAML-based service provider. The scripts are designed to be:

- ✅ **Generic** - Works with any SAML SSO application (Keeper, Okta, etc.)
- ✅ **Idempotent** - Safe to run multiple times
- ✅ **Automated** - Minimal manual steps required
- ✅ **Flexible** - Configurable application names and identifiers

### What the Scripts Automate

1. ✅ Creates or finds the enterprise application in Azure AD
2. ✅ Configures SAML 2.0 single sign-on settings
3. ✅ Sets up the Sign-on URL with IdP Initiated Login Endpoint
4. ✅ Configures user attributes and claims
5. ✅ Downloads Federation Metadata XML
6. ✅ Configures user assignment settings
7. ✅ Assigns users and groups to the application
8. ✅ Automatically renews expiring SAML certificates

## Prerequisites

### Before Running the Scripts

1. **Service Provider Configuration** (MUST be completed first):
   - Configure SSO in your service provider's admin console
   - Download the **Service Provider Metadata** XML file
   - Obtain the IdP Initiated Login Endpoint URL

2. **Azure AD Permissions**:
   - Global Administrator OR Application Administrator role
   - Access to Azure Portal ([portal.azure.com](https://portal.azure.com) or [portal.azure.us](https://portal.azure.us) for Government)

3. **PowerShell Requirements**:
   - PowerShell 5.1 or PowerShell 7+
   - Microsoft.Graph PowerShell module (script will install if missing)
   - Internet connection

## Installation

1. Clone or download this repository
2. Ensure you have the Service Provider metadata XML file ready

## Usage

### Configure-EntraIdSSO.ps1

#### Basic Usage (Keeper Password Manager Example)

```powershell
.\Configure-EntraIdSSO.ps1 `
    -MetadataFile "C:\Path\To\keeper-metadata.xml" `
    -IdPInitiatedLoginEndpoint "https://keepersecurity.com/api/rest/sso/ext_login/YOUR_ID" `
    -EnterpriseDomain "mycompany"
```

#### Generic SSO Application

```powershell
.\Configure-EntraIdSSO.ps1 `
    -MetadataFile "C:\Path\To\app-metadata.xml" `
    -IdPInitiatedLoginEndpoint "https://app.example.com/sso/login" `
    -EnterpriseDomain "mycompany" `
    -ApplicationDisplayName "My SSO Application" `
    -ApplicationIdentifier "MySSOApp"
```

#### With User Assignment

```powershell
.\Configure-EntraIdSSO.ps1 `
    -MetadataFile ".\app-metadata.xml" `
    -IdPInitiatedLoginEndpoint "https://app.example.com/sso/login" `
    -EnterpriseDomain "mycompany" `
    -ApplicationDisplayName "My SSO App" `
    -ApplicationIdentifier "MySSOApp" `
    -UserAssignmentRequired $true `
    -AssignUsersOrGroups @("user1@company.com", "user2@company.com", "IT Security Group")
```

#### For Azure Government Cloud

```powershell
.\Configure-EntraIdSSO.ps1 `
    -MetadataFile ".\app-metadata.xml" `
    -IdPInitiatedLoginEndpoint "https://app.example.com/sso/login" `
    -EnterpriseDomain "mycompany" `
    -ApplicationDisplayName "My SSO App" `
    -GovernmentCloud
```

#### Idempotent Execution (Re-running the Script)

The script is **idempotent** and safe to run multiple times:

```powershell
# First run - creates everything
.\Configure-EntraIdSSO.ps1 -MetadataFile "app.xml" `
    -IdPInitiatedLoginEndpoint "https://..." -EnterpriseDomain "company" `
    -ApplicationDisplayName "My App" -ApplicationIdentifier "MyApp" `
    -AssignUsersOrGroups @("user@company.com")

# Second run - updates configuration without errors
.\Configure-EntraIdSSO.ps1 -MetadataFile "app.xml" `
    -IdPInitiatedLoginEndpoint "https://..." -EnterpriseDomain "company" `
    -ApplicationDisplayName "My App" -ApplicationIdentifier "MyApp" `
    -AssignUsersOrGroups @("user@company.com") `
    -Force  # Skip confirmation prompt
```

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

## Parameters

### Configure-EntraIdSSO.ps1

| Parameter | Required | Description | Default |
|-----------|----------|-------------|---------|
| `MetadataFile` | Yes | Path to Service Provider metadata XML file | - |
| `IdPInitiatedLoginEndpoint` | Yes | IdP Initiated Login Endpoint URL | - |
| `EnterpriseDomain` | Yes | Enterprise domain configured in your app | - |
| `ApplicationDisplayName` | No | Display name for the Azure AD enterprise app | "Keeper Password Manager & Digital Vault" |
| `ApplicationIdentifier` | No | Identifier for searching/identifying the app | "Keeper" |
| `OutputDirectory` | No | Where to save Federation Metadata XML | Current directory |
| `UserAssignmentRequired` | No | Require user assignment to app | true |
| `AssignUsersOrGroups` | No | Array of users/groups to assign | Empty array |
| `GovernmentCloud` | No | Use Azure Government Cloud | false |
| `SkipClaimsCleanup` | No | Skip cleaning up additional claims | false |
| `Force` | No | Skip confirmation prompts for automation | false |

### Renew-SamlCertificate.ps1

| Parameter | Description | Default |
|-----------|-------------|---------  |
| `-RenewDays` | Days before expiration to trigger renewal | 30 |
| `-ApplicationName` | Filter to specific application | All SAML apps |
| `-OutputDirectory` | Where to save new metadata files | Current directory |
| `-DryRun` | Test mode - no changes made | False |
| `-Force` | Force renewal even if not expiring | False |
| `-Quiet` | Minimal output for scheduled tasks | False |
| `-GovernmentCloud` | Use Azure Government Cloud | False |

## Output

### Configure-EntraIdSSO.ps1

Creates:
1. **Log File**: `EntraIdSSO-Setup-YYYYMMDD-HHMMSS.log`
2. **Federation Metadata**: `azure-federation-metadata-YYYYMMDD-HHMMSS.xml`

### Renew-SamlCertificate.ps1

Creates:
1. **Log File**: `SamlCertRenewal-YYYYMMDD-HHMMSS.log`
2. **Metadata Files**: Dated subfolders with `azure-federation-metadata.xml`

**Exit Codes:**
- `0`: Success (certificates checked, renewals completed)
- `1`: No certificates needed renewal
- `2`: Some renewals failed
- `3`: Authentication failed
- `4`: No applications found

## Manual Steps Still Required

After running **Configure-EntraIdSSO.ps1**, you must:

1. **Upload Azure Metadata to Service Provider**:
   - Open your service provider's admin console
   - Navigate to SSO/SAML configuration
   - Select "Azure AD" or "Entra ID" as Identity Provider
   - Upload the downloaded `azure-federation-metadata-*.xml` file

2. **Verify Azure Portal Configuration**:
   - Check User Attributes & Claims section
   - Delete any unnecessary additional claims
   - Verify Email claim uses correct attribute

3. **Test SSO Connection**:
   - Assign a test user
   - Have them login via SSO
   - Verify authentication works

4. **Set Certificate Renewal Reminder**:
   - Azure AD SAML certificates expire after 1 year
   - Set a calendar reminder for 11 months from now
   - OR schedule Renew-SamlCertificate.ps1 to run automatically

After running **Renew-SamlCertificate.ps1**, you must:

1. **Upload New Metadata** to your service provider's admin console
2. **Test SSO** - Verify users can authenticate
3. **Monitor Logs** - Check the generated log files for any issues

## Troubleshooting

### Permission Issues

```powershell
# Run PowerShell as Administrator
# Reconnect with explicit permissions
Connect-MgGraph -Scopes "Application.ReadWrite.All","Directory.ReadWrite.All","User.Read.All","Group.Read.All"
```

### Module Installation Issues

```powershell
# Install manually with elevated privileges
Install-Module Microsoft.Graph -Scope AllUsers -Force
```

### Certificate Not Generated

If the script completes but no certificate appears in Azure:
1. Wait 2-5 minutes
2. Refresh the Azure portal page
3. Navigate to: Enterprise Applications > Your App > Single sign-on > SAML Signing Certificate

### User Assignment Issues

If users can't login:
1. Check that users are assigned to the application
2. Verify "User assignment required" setting matches your needs
3. Ensure users exist in Azure AD

## Important Notes

### Certificate Expiration

⚠️ **IMPORTANT**: Azure AD SAML signing certificates expire after 1 year.

**Options:**
- Set a calendar reminder to manually renew 11 months from now
- Schedule `Renew-SamlCertificate.ps1` to run automatically (recommended)

### User Principal Name vs Email

If your `user.userprincipalname` (UPN) differs from the user's actual email address:
1. Go to Azure Portal > Enterprise Applications > Your App > Single sign-on
2. Edit the Email claim
3. Change from `user.userprincipalname` to `user.mail`

## Supported Applications

This script works with **any SAML 2.0 compatible SSO application**, including:

- Keeper Password Manager
- Okta
- OneLogin
- Auth0
- Custom SAML applications
- Any service provider that uses SAML 2.0 authentication

Simply provide the appropriate:
- Service Provider metadata XML file
- IdP Initiated Login Endpoint
- Application display name and identifier

## Version History

- **2.0** (2025-11-06): Generalized for any SAML SSO application
  - Removed Keeper-specific dependencies
  - Added ApplicationDisplayName and ApplicationIdentifier parameters
  - Simplified logging (removed centralized module)
  - Renamed scripts: Configure-EntraIdSSO.ps1, Renew-SamlCertificate.ps1
  - Updated all documentation

- **1.3** (2025-11-06): Centralized logging module
  - Added KeeperLogging.psm1 for consistent logging
  - Both scripts use centralized logging with fallback

- **1.2** (2025-11-06): Idempotency improvements
  - Added -Force parameter
  - Made user/group assignment idempotent
  - Safe to re-run for configuration updates

- **1.1** (2025-11-06): Certificate renewal feature
  - Added Update-KeeperSAMLCertificate.ps1
  - Certbot-style automatic renewal
  - Schedulable via Task Scheduler or cron

- **1.0** (2025-11-06): Initial Keeper-specific release
  - Automated Azure AD configuration
  - SAML 2.0 setup
  - User and group assignment

## License

This script is provided as-is for use with SAML SSO applications.

## Contributing

Feel free to submit issues or pull requests for improvements.

---

**Generated for Microsoft Entra ID SAML SSO Automation**
