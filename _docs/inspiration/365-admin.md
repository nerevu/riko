# Microsoft 365 Admin Scripts

A collection of PowerShell scripts for Microsoft 365 administration, focusing on Teams channel management, audit logging, and system backup operations.

## Overview

These scripts provide a structured, professional approach to common Microsoft 365 administrative tasks with proper error handling, logging, and single-responsibility design patterns.

## Features

- **Service Connections**: Connect to Exchange Online, Microsoft Teams, and Microsoft Graph
- **Teams Channel Management**: List all channels in a team
- **Teams Channel Member Management**: Add, remove, and list channel members
- **Backup Owner Management**: Automatically add backup owners to channels where a user is the sole owner or member
- **Audit Log Search**: Search unified audit logs for member operations
- **Channel Unarchive**: Restore archived Teams channels
- **System Backup**: Export system drivers and installed programs

## Prerequisites

- Windows PowerShell 5.1 or PowerShell 7+
- Administrator privileges (for some operations)
- Microsoft 365 account with appropriate permissions:
  - Teams Administrator or Owner role (for Teams operations)
  - Exchange Administrator (for audit log searches)
  - Appropriate Graph API permissions

## Installation

Clone or download this repository. Each script will automatically install required PowerShell modules if they are not already present.

## Usage

### 1. Connect to Microsoft 365 Services

```powershell
# Connect to all services (default)
.\Connect-M365Services.ps1

# Connect to specific services
.\Connect-M365Services.ps1 -Services Teams, Graph
```

**Required Graph API Scopes**:

The default connection includes all required scopes for full functionality:
- `Team.ReadBasic.All` - Read basic team information
- `Channel.ReadBasic.All` - Read basic channel information
- `ChannelMember.ReadWrite.All` - Read and write channel members
- `ChannelSettings.ReadWrite.All` - Read and write channel settings (archiving/unarchiving)

These scopes provide a complete superset of all permissions needed, eliminating the need to disconnect and reconnect when switching between different operations.

**Troubleshooting**: If you encounter permission errors after connecting with custom scopes:

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

### 3. Get Team Channel Members

```powershell
.\Get-TeamChannelMembers.ps1 -TeamId <team-id> -ChannelId <channel-id>
```

### 4. Add Team Channel Member

```powershell
# Using Graph API as member (default)
.\Add-TeamChannelMember.ps1 -TeamId <team-id> -ChannelId <channel-id> -UPN "user@domain.com"

# Using Graph API as owner
.\Add-TeamChannelMember.ps1 -TeamId <team-id> -ChannelId <channel-id> -UPN "user@domain.com" -AsOwner

# Using Teams cmdlet (channel name is looked up automatically)
.\Add-TeamChannelMember.ps1 -TeamId <team-id> -ChannelId <channel-id> -UPN "user@domain.com" -UseTeamsMethod
```

### 5. Remove Team Channel Member

```powershell
.\Remove-TeamChannelMember.ps1 -TeamId <team-id> -ChannelId <channel-id> -UPN "user@domain.com"
```

### 6. Add Backup Channel Owner

```powershell
# Add backup owner to channels where user is sole owner or sole member
.\Add-BackupChannelOwner.ps1 -TeamId <team-id> -UPN1 "john@domain.com" -UPN2 "admin@domain.com"

# Preview changes without making them (dry run)
.\Add-BackupChannelOwner.ps1 -TeamId <team-id> -UPN1 "john@domain.com" -UPN2 "admin@domain.com" -DryRun

# Skip archived channels
.\Add-BackupChannelOwner.ps1 -TeamId <team-id> -UPN1 "john@domain.com" -UPN2 "admin@domain.com" -HideArchived
```

### 7. Search Audit Logs

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

# Filter results by username (partial match)
.\Search-TeamMemberAuditLog.ps1 -Ago '30d' -UserName "john@"

# Filter results by specific channel ID
.\Search-TeamMemberAuditLog.ps1 -Ago '7d' -ChannelId "19:abcd1234..."

# Combine multiple filters and export to CSV
.\Search-TeamMemberAuditLog.ps1 -Ago '30d' -ChannelName "Sales" -UserName "admin" -Export
```

**Ago Parameter Format:**
- Hours: `24h`, `48h`
- Days: `7d`, `30d`
- Weeks: `2w`, `4w`
- Months: `3M`, `6M`

**Filter Options:**
- `-ChannelId`: Exact channel ID match
- `-ChannelName`: Partial channel name match (case-insensitive)
- `-UserName`: Partial username match (case-insensitive)
- Filters can be combined with AND logic

### 8. Unarchive Channel

```powershell
.\Invoke-TeamChannelUnarchive.ps1 -TeamId <team-id> -ChannelId <channel-id>
```

### 9. Export System Backup

```powershell
# Export both drivers and programs
.\Export-SystemBackup.ps1 -DestinationPath "D:\Backup"

# Export only drivers
.\Export-SystemBackup.ps1 -ExportDrivers -DestinationPath "D:\Backup"

# Export only installed programs
.\Export-SystemBackup.ps1 -ExportPrograms -DestinationPath "D:\Backup"
```

## Architecture

### Script Design Patterns

All scripts follow these PowerShell best practices:

- **Comment-based help**: Each script and function includes `.SYNOPSIS`, `.DESCRIPTION`, `.PARAMETER`, and `.OUTPUTS` documentation
- **Single return point**: Functions return once at the end with a result variable
- **Return-based error handling**: Functions return success/failure indicators instead of throwing exceptions
- **Consistent logging**: Uses the shared `Write-Log` function with severity levels (Info, Warning, Error, Success, Debug)
- **Explicit parameter types**: All parameters have proper type declarations and validation
- **Single exit point**: Main execution blocks exit once with an appropriate exit code

### Shared Utilities Module

`M365AdminUtils.psm1` provides common functions:

- `Write-Log`: Consistent logging with color-coded severity levels
- `Test-ModuleInstalled`: Check if PowerShell modules are installed
- `Test-CommandAvailable`: Verify command availability
- `Format-TeamChannelId`: Format channel IDs for Graph API
- `Format-UserPrincipalName`: Format user principal names

## Error Handling

All scripts use graceful error handling:

- Return values indicate success (`$true`/`0`) or failure (`$false`/`1`)
- Errors are logged with appropriate severity levels
- Scripts exit with code `0` on success, `1` on failure
- Known issues (like the `Remove-TeamChannelUser` NullReferenceException) are handled with verification logic

## References

- [Microsoft Graph API - Teams](https://docs.microsoft.com/en-us/graph/api/resources/teams-api-overview)
- [Add Members to Microsoft Team Channel with Graph PowerShell](https://m365corner.com/m365-powershell/add-members-to-microsoft-team-channel-with-graph-powershell.html)
- [Using Add-MgTeamMember in Graph PowerShell](https://m365corner.com/m365-powershell/using-add-mgteammember-in-graph-powershell.html)
- [Reclaiming a Private Channel After All Members Are Removed](https://www.reddit.com/r/MicrosoftTeams/comments/gf6jfq/reclaiming_a_private_channel_after_all_members/)
- [Can I Recover a Deleted Microsoft Teams Channel](https://debug.to/6868/can-i-recover-a-deleted-microsoft-teams-channel)
- [Disable Azure AD Accounts in Teams](https://practical365.com/disable-azure-ad-accounts-teams/)

## License

MIT License - see LICENSE file for details.

## Author

Reuben Cummings (reubano@gmail.com)

## Contributing

Contributions are welcome! Please ensure any new scripts follow the established patterns and include proper documentation.
