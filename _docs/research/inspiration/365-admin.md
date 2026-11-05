---
source: ../../../../365-admin/README.md
---

# Microsoft 365 Admin Scripts

A collection of PowerShell scripts for Microsoft 365 administration, focusing on Teams
channel management, audit logging, and system backup operations.

## Overview

These scripts provide a structured, professional approach to common Microsoft 365
administrative tasks with proper error handling, logging, and single-responsibility
design patterns.

None of the scripts has a dry-run, preview, or `WhatIf` mode. Every script that changes
Teams membership or channel state applies the change as soon as it runs. The Teams
scripts do not re-read state after a write to confirm it took effect. They check the
current membership *before* acting (see [Membership rules](#membership-rules)) and trust
the API response afterwards. Only `Add-Office365.ps1` and `Remove-Office365.ps1`
re-check the machine state after their change.

## Features

- **Service Connections**: Connect to Exchange Online, Microsoft Teams, and Microsoft
  Graph
- **Teams Channel Management**: List all channels in a team
- **Teams Channel Member Management**: Add, remove, and list channel members, and list
  one user's channels
- **Backup Owner Management**: Add a backup owner to channels where a user is the only
  owner
- **Membership Mirroring**: Give one user the same channel memberships and ownerships as
  another
- **Audit Log Search**: Search unified audit logs for member operations
- **Channel Unarchive**: Restore archived Teams channels
- **System Backup**: Export system drivers and installed programs
- **Machine scripts**: Install or remove Microsoft 365 Apps and check the Teams install
  on a Windows machine

## Script inventory

| Script | Parameters | Changes state? | Uses `M365AdminUtils.psm1`? |
| --- | --- | --- | --- |
| `Connect-M365Services.ps1` | `[-Services ExchangeOnline,Teams,Graph,All]` | no | yes |
| `Get-TeamChannels.ps1` | `-TeamId [-HideArchived]` | no | yes |
| `Get-TeamChannelMembers.ps1` | `-TeamId -ChannelId` | no | yes |
| `Get-MemberTeamChannels.ps1` | `-UPN -TeamId [-HideArchived]` | no | yes |
| `Get-UserTeams.ps1` | none | no | yes |
| `Add-TeamChannelMember.ps1` | `-TeamId (-ChannelId \| -ChannelName) -UPN [-AsOwner] [-UseTeamsMethod]` | yes | yes |
| `Remove-TeamChannelMember.ps1` | `-TeamId -ChannelId -UPN` | yes | yes |
| `Add-BackupChannelOwner.ps1` | `-TeamId -MemberUPN -BackupUPN [-HideArchived]` | yes | yes |
| `Invoke-MirrorTeamChannels.ps1` | `-MemberUPN -ModifyUPN [-TeamId] [-HideArchived]` | yes | yes |
| `Invoke-TeamChannelUnarchive.ps1` | `-TeamId -ChannelId` | yes | yes |
| `Search-TeamMemberAuditLog.ps1` | `[-Ago] \| -StartDate -EndDate`, `[-Operations] [-ResultSize] [-ChannelId] [-ChannelName] [-UPN] [-IncludeGroupChat] [-Export]` | no | yes |
| `Export-SystemBackup.ps1` | `[-DestinationPath] [-ExportDrivers] [-ExportPrograms]` | writes files | yes (logging only) |
| `Get-Calendar.ps1` | none (hard-coded calls) | no | no |
| `Check-TeamsHealth.ps1` | none | no | no |
| `Add-Office365.ps1` | none (variables at the top of the file) | yes (machine) | no |
| `Remove-Office365.ps1` | none (variables at the top of the file) | yes (machine) | no |

## Prerequisites

- Windows PowerShell 5.1 or PowerShell 7+ (`Export-SystemBackup.ps1` lists programs with
  `Get-WmiObject`, a Windows PowerShell 5.1 cmdlet)
- Administrator privileges (for some operations; `Add-Office365.ps1` and
  `Remove-Office365.ps1` must run as Administrator or SYSTEM)
- Microsoft 365 account with appropriate permissions:
  - Teams Administrator or Owner role (for Teams operations)
  - Exchange Administrator (for audit log searches)
  - Appropriate Graph API permissions

## Installation

Clone or download this repository. The scripts that import `M365AdminUtils.psm1` call
`Install-Prerequisites` for the PowerShell modules they need. That function:

- installs the NuGet package provider if it is missing;
- marks the PowerShell Gallery as trusted if it is not registered as a package source;
- installs each missing module from the Gallery for the current user, then imports it.

Some scripts pin versions: `Add-TeamChannelMember.ps1`, `Invoke-MirrorTeamChannels.ps1`,
`Get-MemberTeamChannels.ps1` and `Get-UserTeams.ps1` require
`Microsoft.Graph.Users`/`Microsoft.Graph.Teams` 2.34.0 and/or `MicrosoftTeams` 7.5.0.
The last three also pin `Microsoft.Graph.Authentication` 2.34.0.

`Connect-M365Services.ps1` calls `Install-Prerequisites` only *after* its connection
attempts, and ignores the result (`Connect-M365Services.ps1:85`), so `MicrosoftTeams`
and `ExchangeOnlineManagement` must already be present for its first run to connect
(`Connect-GraphWithScopes` installs `Microsoft.Graph.Authentication` itself).
`Get-Calendar.ps1` runs `Install-Module … -Force` for its two modules every time it is
loaded.

## Usage

### 1. Connect to Microsoft 365 Services

```powershell
# Connect to all services (default)
.\Connect-M365Services.ps1

# Connect to specific services
.\Connect-M365Services.ps1 -Services Teams, Graph
```

**Required Graph API Scopes**:

The default connection (`Connect-GraphWithScopes`) requests these scopes:

- `Group.Read.All` - Read groups
- `Team.ReadBasic.All` - Read basic team information
- `Channel.ReadBasic.All` - Read basic channel information
- `ChannelMember.ReadWrite.All` - Read and write channel members
- `ChannelSettings.ReadWrite.All` - Read and write channel settings
  (archiving/unarchiving)

Every Teams script calls `Connect-GraphWithScopes` itself. If the current Graph session
already holds these scopes (a `ReadWrite` scope also counts as its `Read` scope), it
reuses the session; otherwise it calls `Connect-MgGraph` with the list above. These
scopes are meant to be a complete superset of all permissions needed, eliminating the
need to disconnect and reconnect when switching between different operations.

**Troubleshooting**: If you encounter permission errors after connecting with custom
scopes:

```powershell
Disconnect-MgGraph
.\Connect-M365Services.ps1  # Reconnects with all required scopes
```

### 2. Get Team Channels

```powershell
# List all channels in a team (including archived)
.\Get-TeamChannels.ps1 -TeamId <team-id>

# List only active channels (hide archived)
.\Get-TeamChannels.ps1 -TeamId <team-id> -HideArchived
```

Prints a table of `DisplayName, Id, MembershipType, IsArchived`. The `Id` column is the
cleaned channel id, without the `19:` prefix or the `@thread.tacv2` suffix. The
channel-management scripts accept either form, because `Format-TeamChannelId` adds them
back; the audit search's `-ChannelId` filter does not (see Known issues). Exits 1 when
no channels are found.

### 3. Get Team Channel Members

```powershell
.\Get-TeamChannelMembers.ps1 -TeamId <team-id> -ChannelId <channel-id>
```

This script always uses the Teams cmdlet (`Get-TeamChannelUser`), so it signs in to
Microsoft Teams as well as Graph. It prints `User, Name, Role`.

### 4. List a User's Channels in a Team

```powershell
.\Get-MemberTeamChannels.ps1 -TeamId <team-id> -UPN "user@domain.com"

# Skip archived channels
.\Get-MemberTeamChannels.ps1 -TeamId <team-id> -UPN "user@domain.com" -HideArchived
```

Checks every channel's member list and prints
`ChannelName, ChannelId, MembershipType, Role, IsArchived` for each channel the user
belongs to. `Role` is `owner` or `member`.

### 5. List the Current User's Teams

```powershell
.\Get-UserTeams.ps1
```

Prints `DisplayName, Id` for the joined teams of one user. It finds that user by
stripping `[`, `]` and spaces from each user's display name and comparing the result to
`$env:USERNAME` (`Get-UserTeams.ps1:34-36`). It queries Graph with `Get-MgUser` but does
not use the signed-in account's identity to pick the user.

### 6. Add Team Channel Member

```powershell
# Using Graph API as member (default)
.\Add-TeamChannelMember.ps1 -TeamId <team-id> -ChannelId <channel-id> -UPN "user@domain.com"

# Using Graph API as owner
.\Add-TeamChannelMember.ps1 -TeamId <team-id> -ChannelId <channel-id> -UPN "user@domain.com" -AsOwner

# Select the channel by name instead of id
.\Add-TeamChannelMember.ps1 -TeamId <team-id> -ChannelName "Sales Team" -UPN "user@domain.com"

# Using Teams cmdlet (channel name is looked up automatically)
.\Add-TeamChannelMember.ps1 -TeamId <team-id> -ChannelId <channel-id> -UPN "user@domain.com" -UseTeamsMethod
```

`-ChannelName` is a case-insensitive partial match (`*name*`) in strict mode. If more
than one channel matches, the script logs the matching names and exits 1 without
changing anything.

The script is a desired-state upsert (`Set-TeamChannelMemberRole`); see
[Membership rules](#membership-rules).

### 7. Remove Team Channel Member

```powershell
.\Remove-TeamChannelMember.ps1 -TeamId <team-id> -ChannelId <channel-id> -UPN "user@domain.com"
```

This script uses the Graph API, not `Remove-TeamChannelUser` (the script's own header is
out of date). It reads the channel's members, finds the one whose `email` or
`userPrincipalName` equals `-UPN`, and sends a Graph `DELETE` for that membership. If
the user is not a member, it logs a warning and exits 1. It does not re-read the member
list after the delete.

### 8. Add Backup Channel Owner

```powershell
# Add a backup owner to channels where the user is the only owner
.\Add-BackupChannelOwner.ps1 -TeamId <team-id> -MemberUPN "john@domain.com" -BackupUPN "admin@domain.com"

# Skip archived channels
.\Add-BackupChannelOwner.ps1 -TeamId <team-id> -MemberUPN "john@domain.com" -BackupUPN "admin@domain.com" -HideArchived
```

There is no dry-run or preview option. The script's second help example says it "shows
which channels would have the backup owner added without making changes", but it uses
the same arguments as the first example and makes the changes. The intended preview (the
script rejects `-DryRun` today):

```powershell
# Preview changes (intended; not implemented)
.\Add-BackupChannelOwner.ps1 -TeamId <team-id> -MemberUPN "john@domain.com" -BackupUPN "admin@domain.com" -DryRun
```

For each channel, `-BackupUPN` is made an owner (added or promoted, see
[Membership rules](#membership-rules)) only when `-MemberUPN` is an owner of the channel
*and* the channel has exactly one owner. A channel where `-MemberUPN` is the only member
but not an owner is skipped. The script ends with counts of channels processed, updated,
skipped and erred, and exits 1 if any channel erred.

### 9. Mirror Channel Memberships

```powershell
.\Invoke-MirrorTeamChannels.ps1 -TeamId <team-id> -MemberUPN "john@domain.com" -ModifyUPN "bob@domain.com"
```

`-MemberUPN` is the template user and `-ModifyUPN` is the user to change. For each
channel:

| Template user | User to change | Action |
| --- | --- | --- |
| not in channel | any | skip |
| in channel | not in channel | add with the template user's role (owner or member) |
| owner | member (not owner) | promote to owner |
| any other combination | | skip |

The script never removes memberships and never demotes. If `-TeamId` is omitted, it uses
the first joined team of the user found by the `$env:USERNAME` display-name match
described under `Get-UserTeams.ps1`, not of `-MemberUPN`. Exits 1 if any channel erred.

### 10. Search Audit Logs

```powershell
# Search for member operations in the last 24 hours (default)
.\Search-TeamMemberAuditLog.ps1

# Search for member operations in the last 7 days
.\Search-TeamMemberAuditLog.ps1 -Ago '7d'

# Search for member operations in the last 2 weeks
.\Search-TeamMemberAuditLog.ps1 -Ago '2w'

# Search for member operations in the last 3 months
.\Search-TeamMemberAuditLog.ps1 -Ago '3M'

# Search for member operations between specific dates
.\Search-TeamMemberAuditLog.ps1 -StartDate "01-Nov-2025" -EndDate "07-Nov-2025"

# Search for specific operations in the last 7 days
.\Search-TeamMemberAuditLog.ps1 -Ago '7d' -Operations "MemberRemoved", "MemberAdded"

# Filter results by channel name (partial match)
.\Search-TeamMemberAuditLog.ps1 -Ago '7d' -ChannelName "Marketing"

# Filter results by user (partial match)
.\Search-TeamMemberAuditLog.ps1 -Ago '30d' -UPN "john@"

# Filter results by specific channel ID (cleaned form, as printed by Get-TeamChannels.ps1)
.\Search-TeamMemberAuditLog.ps1 -Ago '7d' -ChannelId "abcd1234..."

# Raise the row cap and include group chat records
.\Search-TeamMemberAuditLog.ps1 -Ago '30d' -ResultSize 5000 -IncludeGroupChat

# Combine multiple filters and export to CSV (intended; -Export writes no file today, see Known issues)
.\Search-TeamMemberAuditLog.ps1 -Ago '30d' -ChannelName "Sales" -UPN "admin" -Export
```

The script signs in to Graph (`Connect-GraphWithScopes`) before it connects to Exchange
Online, so it needs both sign-ins. The query itself is `Search-UnifiedAuditLog`.

**Parameters:**

| Parameter | Default | Notes |
| --- | --- | --- |
| `-Ago` | `24h` | Must match `^(\d+)([hdwM])$`. Cannot be combined with `-StartDate`/`-EndDate`. |
| `-StartDate`, `-EndDate` | none | Both required together; passed to `Search-UnifiedAuditLog` as given |
| `-Operations` | `MemberRoleChanged, MemberRemoved, ChannelAdded, ChannelDeleted, MemberAdded, TeamDeleted, TeamCreated` | |
| `-ResultSize` | `1000` | Maximum rows requested from the audit log. Matches beyond this cap are dropped without a warning, and the filters below run only on the returned rows. |
| `-ChannelId` | none | Exact match against the cleaned channel id |
| `-ChannelName` | none | Case-insensitive partial match |
| `-UPN` | none | Case-insensitive partial match against the comma-joined member UPNs |
| `-IncludeGroupChat` | off | By default, records with `CommunicationType` `GroupChat` are dropped after filtering |
| `-Export` | off | Does not write a file; see Known issues |

**Ago Parameter Format:**

- Hours: `24h`, `48h`
- Days: `7d`, `30d`
- Weeks: `2w`, `4w` (7 days each)
- Months: `3M`, `6M` (calendar months; uppercase `M` only)

The window runs from that offset back from now until now, formatted as
`MM/dd/yyyy HH:mm:ss`.

**Filter Options:**

- `-ChannelId`: Exact channel ID match
- `-ChannelName`: Partial channel name match (case-insensitive)
- `-UPN`: Partial username match (case-insensitive)
- Filters can be combined with AND logic

#### Output fields

Each audit record is parsed from its `AuditData` JSON into one object with these fields:

| Field | Source |
| --- | --- |
| `CreationDate`, `Operations`, `RecordType` | the audit record |
| `TeamName`, `CommunicationType`, `ChannelName`, `Members`, `AADGroupId` | `AuditData` |
| `UserIds` | `AuditData.Members[].UPN`, comma-joined, or `N/A` |
| `Roles` | `AuditData.Members[].Role` with `1` → `Owner`, `2` → `Member`, other values as-is, or `N/A` |
| `TeamGuid` | `AuditData.TeamGuid`, cleaned, or `N/A` |
| `ChannelId` | `AuditData.ChannelGuid`, cleaned, or `N/A` |

A record whose `AuditData` cannot be parsed is kept unchanged and a warning is logged.

The results are grouped by `ChannelId` and sorted by it. Each group prints a header
(Team, Team ID, Channel, Channel ID, Record Count) followed by a table of
`Date, Operations, UserIds, Type, Roles`.

The script exits 1 when the audit log returns no rows. It exits 0 when rows were
returned, even if the filters removed them all.

### 11. Unarchive Channel

```powershell
.\Invoke-TeamChannelUnarchive.ps1 -TeamId <team-id> -ChannelId <channel-id>
```

### 12. Export System Backup

```powershell
# Export both drivers and programs
.\Export-SystemBackup.ps1 -DestinationPath "D:\Backup"

# Export only drivers
.\Export-SystemBackup.ps1 -ExportDrivers -DestinationPath "D:\Backup"

# Export only installed programs
.\Export-SystemBackup.ps1 -ExportPrograms -DestinationPath "D:\Backup"
```

`-DestinationPath` defaults to the current directory and is created if it does not
exist. If neither switch is given, both exports run.

- Drivers: `dism /online /export-driver` into `<DestinationPath>\drivers`.
- Programs: `Win32_Product` (`Name, Version, Vendor, InstallDate, InstallLocation`) into
  `<DestinationPath>\installed_programs_<yyyyMMdd-HHmmss>.csv`.

### 13. Machine Scripts

These scripts do not import `M365AdminUtils.psm1` and take no parameters.

- **`Check-TeamsHealth.ps1`** reports the newest provisioned `MSTeams` AppX package and
  the newest installed one whose `AppxManifest.xml` exists. It prints `HEALTHY` and
  exits 0 when a valid installed package exists. It prints `REMEDIATION REQUIRED` and
  exits 1 when the package is provisioned but its payload is missing (suggesting
  `teamsbootstrapper.exe -p`), or when Teams is absent. It exits 1 on any error.
- **`Add-Office365.ps1`** is a desired-state installer for Microsoft 365 Apps, written
  for an RMM agent. Its settings are variables at the top of the file: `$ProductId`
  (default `O365ProPlusRetail`), `$DesiredChannel` (`Current`), `$ForceCloseOfficeApps`
  and `$RemoveLegacyMSIOffice` (both `$false`). The run goes like this:
  - If WinGet reports `Microsoft.Office`, it only makes sure Teams is provisioned and
    exits 0.
  - If the right product is already on Current Channel, it does the same.
  - Otherwise it downloads the Office Deployment Tool and checks that it carries a valid
    Microsoft Authenticode signature, keeps the existing architecture (or uses 64-bit),
    and runs setup.
  - After setup it re-reads the Click-to-Run registry and fails if the product or
    Current Channel is not detected.
  - Last, it provisions Teams with the signed Teams bootstrapper (`-p`) and re-checks
    that the payload exists.
  - Exit 0 means the desired state was reached; 1 means it failed.
- **`Remove-Office365.ps1`** removes only `$ProductId` and keeps other Click-to-Run
  products such as Visio and Project. It exits 0 at once if the product is absent.
  Otherwise it downloads and signature-checks the Office Deployment Tool, runs the
  removal, re-reads the installed products, and fails if the product is still
  registered. It exits 0 or 1.
- Both Office scripts write their own log under `%ProgramData%\Nerevu\M365Deploy\`
  (`M365Deploy.log` / `M365Uninstall.log`).
- **`Get-Calendar.ps1`** is a working script rather than a reusable command. At load it
  installs `Microsoft.Graph.Applications` and `ExchangeOnlineManagement`, then connects
  to Graph (`Calendars.Read.Shared`, `User.Read.All`) and Exchange Online. It defines
  `Find-EXOCalendar <User> <Search>`, which lists a mailbox's calendars whose names
  contain the search text and infers each calendar's owner and type from the owner's
  calendars and Exchange recipient. The file ends with three hard-coded calls against
  one mailbox.

## Membership rules

All membership writes go through `Set-TeamChannelMemberRole` in `M365AdminUtils.psm1`.
It first reads the channel's members (or uses the list it was given) and finds the user
by `email` or `userPrincipalName`:

| Current state | Action |
| --- | --- |
| user has the requested role | nothing; returns success |
| user is a member with a different role | remove, then add again with the new role (`Update-TeamChannelMemberRole`) |
| user is not a member | add with the requested role |

Adds use a Graph `POST` to the channel's `members` collection by default, or
`Add-TeamChannelUser` with `-UseTeamsMethod`. A role change is a remove followed by an
add. If the add fails after the remove succeeded, the user is left removed from the
channel. Nothing is re-read after a write.

## Architecture

### Script Design Patterns

The scripts that import `M365AdminUtils.psm1` (the Teams, audit and backup scripts)
follow these PowerShell practices:

- **Comment-based help**: Each script and function includes `.SYNOPSIS`, `.DESCRIPTION`,
  `.PARAMETER`, and `.OUTPUTS` documentation
- **Single return point**: Functions return once at the end with a result variable
- **Return-based error handling**: Functions return success/failure indicators instead
  of throwing exceptions
- **Consistent logging**: Uses the shared `Write-Log` function with severity levels
  (Info, Warning, Error, Success, Debug)
- **Explicit parameter types**: All parameters have proper type declarations and
  validation
- **Single exit point**: Main execution blocks exit once with an appropriate exit code

The shared `Write-Log` writes `[yyyy-MM-dd HH:mm:ss] [Level] message` to the console
only, color-coded by level. It writes no log file. `Get-Calendar.ps1`,
`Check-TeamsHealth.ps1`, `Add-Office365.ps1` and `Remove-Office365.ps1` do not use it.

### Shared Utilities Module

`M365AdminUtils.psm1` exports these functions:

- `Write-Log`: Consistent logging with color-coded severity levels
- `Merge-HashTable`: Merge hash tables and objects into one object (last key wins)
- `Test-ModuleInstalled`: Check if PowerShell modules are installed
- `Test-CommandAvailable`: Verify command availability
- `Test-TeamsConnection`, `Test-ExchangeConnection`: Check for an existing session
- `Install-Prerequisites`: Install and import modules, optionally at pinned versions
- `Connect-GraphWithScopes`: Reuse or open a Graph session with the default scopes above
- `Connect-TeamsService`, `Connect-ExchangeOnlineService`: Reuse or open a Teams /
  Exchange Online session
- `Format-TeamChannelId`: Format channel IDs for Graph API (`19:<id>@thread.tacv2`)
- `Get-CleanChannelId`: Strip the `19:` prefix and `@thread.tacv2` suffix
- `Format-UserPrincipalName`: Append a default domain to a bare user id
- `Get-AllTeamChannels`: List a team's channels with `IsArchived`, optionally hiding
  archived ones
- `Get-ChannelById`, `Get-ChannelNameFromId`, `Get-ChannelByName`: Channel lookups
  (`Get-ChannelByName` is a partial match, with `-Strict` to reject several matches)
- `Get-TeamChannelMembers`: List members via Graph (with `roles`) or the Teams cmdlet
  (`-UseTeamsMethod`)
- `Add-TeamChannelMemberWithRole`, `Remove-TeamChannelMemberByUPN`,
  `Update-TeamChannelMemberRole`, `Set-TeamChannelMemberRole`: Membership writes (see
  [Membership rules](#membership-rules))

## Error Handling

All scripts use graceful error handling:

- Return values indicate success (`$true`/`0`) or failure (`$false`/`1`)
- Errors are logged with appropriate severity levels
- Scripts exit with code `0` on success, `1` on failure
- There is no special handling or verification for `Remove-TeamChannelUser`.
  `Remove-TeamChannelMember.ps1` uses the Graph `DELETE` path and does not re-read the
  member list afterwards.
- There is no dry-run or `WhatIf` mode in any script

## References

- [Microsoft Graph API - Teams](https://docs.microsoft.com/en-us/graph/api/resources/teams-api-overview)
- [Add Members to Microsoft Team Channel with Graph PowerShell](https://m365corner.com/m365-powershell/add-members-to-microsoft-team-channel-with-graph-powershell.html)
- [Using Add-MgTeamMember in Graph PowerShell](https://m365corner.com/m365-powershell/using-add-mgteammember-in-graph-powershell.html)
- [Reclaiming a Private Channel After All Members Are Removed](https://www.reddit.com/r/MicrosoftTeams/comments/gf6jfq/reclaiming_a_private_channel_after_all_members/)
- [Can I Recover a Deleted Microsoft Teams Channel](https://debug.to/6868/can-i-recover-a-deleted-microsoft-teams-channel)
- [Disable Azure AD Accounts in Teams](https://practical365.com/disable-azure-ad-accounts-teams/)

## Known issues

- `-Export` writes no CSV. `$exportPath` is never assigned, so `Export-AuditResults` is
  called with an empty mandatory `-OutputPath` (`Search-TeamMemberAuditLog.ps1:565`).
  The `AuditLog_[timestamp].csv` name appears only in the help text (`:48`, `:83`). The
  export would also select an `AuditData` column that parsed records no longer carry
  (`:378`).
- `-ChannelId` given with the `19:` prefix or the `@thread.tacv2` suffix never matches.
  Records carry the cleaned id (`Search-TeamMemberAuditLog.ps1:247`), but the parameter
  is compared unchanged (`:436`).
- The "sole member" branch of `Test-ShouldAddBackupOwner` cannot run. A non-owner is
  rejected first (`Add-BackupChannelOwner.ps1:88`), and an owner who is the only member
  already passes the one-owner test (`:97`, `:101`).
- `Add-BackupChannelOwner.ps1:27-30` documents a preview run, but the script has no
  preview option.
- `Remove-TeamChannelMember.ps1:7` says the script uses `Remove-TeamChannelUser`. It
  calls `Remove-TeamChannelMemberByUPN` without `-UseTeamsMethod`, which takes the Graph
  path (`:47`).
- `Invoke-MirrorTeamChannels.ps1` without `-TeamId` looks up the team from
  `$env:USERNAME` (`:149-156`). The error at `:168` says it "could not determine from
  MemberUPN".
- `Get-Calendar.ps1:191-192` are pasted output lines (`CalendarType : …`,
  `MatchMethod : …`), not code. They run as commands after the three hard-coded
  `Find-EXOCalendar` calls (`:186-188`).
- `Test-GraphConnection` is listed in `Export-ModuleMember` (`M365AdminUtils.psm1:1307`)
  but no such function is defined.
- `Connect-M365Services.ps1:85` installs modules after the connection attempts and
  ignores the result.

## License

MIT License - see LICENSE file for details.

## Author

Reuben Cummings (<reubano@gmail.com>)

## Contributing

Contributions are welcome! Please ensure any new scripts follow the established patterns
and include proper documentation.
