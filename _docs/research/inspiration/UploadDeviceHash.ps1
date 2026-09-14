<#
.SYNOPSIS
    Retrieves Windows Autopilot hardware information for device enrollment.

.DESCRIPTION
    This script installs Get-WindowsAutopilotInfo and retrieves hardware ID
    information required for Windows Autopilot device registration. Output can be saved
    to a CSV file or uploaded directly to Microsoft Intune.

.PARAMETER OutputPath
    Directory path where the AutopilotHWID.csv file will be saved.
    Default: C:\HWID

.PARAMETER Online
    If specified, uploads hardware information directly to Microsoft Intune instead
    of saving to a CSV file. Requires authentication to Microsoft Graph.

.PARAMETER InputFile
    CSV file containing device identifier(s).

.PARAMETER GroupTag
    Optional tag value for device organization in Intune (e.g., "IT-Department", "Kiosk").

.PARAMETER AssignedUser
    Optional UPN of the user to be pre-assigned to the device (e.g., "john.doe@contoso.com").
    Automatically sets the -IsAdmin switch.

.PARAMETER AssignedComputerName
    Optional computer name to be assigned to the device during Autopilot deployment.
    Only works with -Online switch.

.PARAMETER Delete
    Remove the device from Intune if it already exists

.PARAMETER IsAdmin
    Mark the device as non-shared. Requires the -AssignedUser switch be set.

.PARAMETER IsMSP
    Mark the device as MSP owned

.PARAMETER Append
    Append to existing CSV file instead of overwriting. Only applies to file output mode.

.PARAMETER Interactive
    May require user interaction. Do not set if performing remote execution via RMM tools.

.PARAMETER TenantId
    Domain or Azure AD Tenant ID for non-interactive authentication. Required when using -Online without -Interactive.

.PARAMETER AppId
    Azure AD App Registration Client ID for non-interactive authentication. Required when using -Online without -Interactive.

.PARAMETER AppSecret
    Azure AD App Registration Client Secret for non-interactive authentication. Required when using -Online without -Interactive
    (unless using -KeyVaultName and -SecretName). Overridden if -KeyVaultName and -SecretName are set.

.PARAMETER KeyVaultName
    Azure Key Vault name containing the app secret. Overrides -AppSecret if -SecretName is also set.

.PARAMETER SecretName
    Name of the secret in Azure Key Vault containing the app registration client secret. Overrides -AppSecret if -KeyVaultName is also set.

.PARAMETER SubscriptionId
    Azure Subscription ID. Optional but recommended for multi-subscription environments.

.EXAMPLE
    .\Get-DeviceHash.ps1
    Saves hardware ID to C:\Windows\Temp\AutopilotHWID.csv

.EXAMPLE
    .\Get-DeviceHash.ps1 -OutputPath "D:\AutopilotData"
    Saves hardware ID to D:\AutopilotData\AutopilotHWID.csv

.EXAMPLE
    .\Get-DeviceHash.ps1 -Online -Interactive
    Uploads hardware ID directly to Microsoft Intune

.EXAMPLE
    .\Get-DeviceHash.ps1
    Runs silently for remote execution, logs to C:\Windows\Temp\AutopilotInfo.log

.EXAMPLE
    .\Get-DeviceHash.ps1 -Online -TenantId "contoso.onmicrosoft.com" -AppId "12345678-1234-1234-1234-123456789012" -AppSecret "your-secret"
    Uploads to Intune silently using app registration credentials

.EXAMPLE
    .\Get-DeviceHash.ps1 -Online -TenantId "contoso.onmicrosoft.com" -AppId "12345678-1234-1234-1234-123456789012" -KeyVaultName "homelab" -SecretName "appreg"
    Uploads to Intune silently, retrieving app secret from Azure Key Vault

.EXAMPLE
    .\Get-DeviceHash.ps1 -Online -Interactive -GroupTag "IT-Department" -AssignedUser "john.doe@contoso.com"
    Uploads to Intune with group tag and pre-assigned user

.EXAMPLE
    .\Get-DeviceHash.ps1 -Online -Interactive -AssignedComputerName "DESKTOP-IT-001" -GroupTag "IT"
    Uploads to Intune with specific computer name and group tag

.EXAMPLE
    .\Get-DeviceHash.ps1 -OutputPath "D:\Autopilot" -Append
    Appends hardware info to existing CSV file in D:\Autopilot directory

.NOTES
    Requires Administrator privileges
    Requires internet connectivity to download Get-WindowsAutopilotInfo
    Version: 2.0
#>

[CmdletBinding(DefaultParameterSetName = 'File')]
param(
    [Parameter(Mandatory = $false, Position = 0)]
    [string] $TenantId = 'centralillinoisfriends.org',

    [Parameter(Mandatory = $False, ValueFromPipeline = $True, ValueFromPipelineByPropertyName = $True, Position = 1)]
    [alias("DNSHostName", "ComputerName", "Computer")]
    [String[]] $Names = @("localhost"),

    [Parameter()]
    [switch] $Interactive,

    [Parameter(ParameterSetName = 'File')]
    [ValidateNotNullOrEmpty()]
    [string] $OutputPath = $(Join-Path $env:TEMP "DeviceHash"),

    [Parameter(ParameterSetName = 'File')]
    [switch] $Append,

    [Parameter()]
    [string] $InputFile,

    [Parameter()]
    [string] $Mode,

    [Parameter()]
    [Switch] $IsAdmin,

    [Parameter()]
    [Switch] $IsMSP,

    [Parameter()]
    [string] $GroupTag = $GroupTag,

    [Parameter(ParameterSetName = 'Online')]
    [switch] $Online = $true,

    [Parameter(ParameterSetName = 'Online')]
    [Switch] $Delete,

    [Parameter(ParameterSetName = 'Online')]
    [Switch] $CleanupAutopilot,

    [Parameter(ParameterSetName = 'Online')]
    [Switch] $UpdateExisting = $false,

    [Parameter(ParameterSetName = 'Online')]
    [string] $AssignedUser = $AssignedUser,

    [Parameter(ParameterSetName = 'Online')]
    [string] $AssignedComputerName,

    [Parameter(ParameterSetName = 'Online')]
    [string] $AppTenantId = $AppTenantId,

    [Parameter(ParameterSetName = 'Online')]
    [string] $AppId = $AppId,

    [Parameter(ParameterSetName = 'Online')]
    [string] $AppSecret = $AppSecret,

    [Parameter(ParameterSetName = 'Online')]
    [string] $KeyVaultName = $KeyVaultName,

    [Parameter(ParameterSetName = 'Online')]
    [string] $SecretName = $SecretName,

    [Parameter(ParameterSetName = 'Online')]
    [string] $SubscriptionId = $SubscriptionId
)

#Requires -RunAsAdministrator

Begin {
    Set-StrictMode -Version Latest
    $ErrorActionPreference = "Stop"

    $LogFilePath = Join-Path $OutputPath "AutopilotInfo.log"
    $OutputLogFilePath = Join-Path $OutputPath "AutopilotOutput.log"
    $ErrorLogFilePath = Join-Path $OutputPath "AutopilotError.log"

    if ($Mode -eq 'community') {
        $ScriptName = "get-windowsautopilotinfocommunity"
        $ScriptVersion = "5.0.11"
    } elseif ($Mode -eq 'native') {
        $ScriptName = "Get-WindowsAutopilotInfo"
        $ScriptVersion = "3.9"
    } else {
        $ScriptName = ""
        $ScriptVersion = ""
    }

    function Write-Log {
        param(
            [Parameter(Mandatory = $true)]
            [string] $Message,

            [Parameter()]
            [ValidateSet('Info', 'Warning', 'Error', 'Success')]
            [string] $Level = 'Info'
        )

        $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        $logEntry = "[$timestamp] [$Level] $Message"

        Add-Content -Path $LogFilePath -Value $logEntry -ErrorAction SilentlyContinue

        $color = switch ($Level) {
            'Info'    { 'White' }
            'Warning' { 'Yellow' }
            'Error'   { 'Red' }
            'Success' { 'Green' }
        }

        Write-Host $logEntry -ForegroundColor $color
    }

    function Get-WUChassisType {
        <#
        .SYNOPSIS
            Get whether the computer is Desktop, Tablet, or Server from ChassisTypes.

        .DESCRIPTION
            Get whether the computer is Desktop, Tablet, or Server from ChassisTypes. Be sure to test in your own environment.

        .OUTPUTS
            System.String

            Returns this computer type. The range of values is 'Desktop', 'Laptop', 'Tablet' or 'Server'.
        #>

        [CmdletBinding()]
        param ()

        Set-StrictMode -Version 'Latest'

        [int[]]$chassisType = Get-CimInstance Win32_SystemEnclosure | Select-Object -ExpandProperty ChassisTypes

        $result = switch ($chassisType) {
            { $_ -in 3, 4, 5, 6, 7, 15, 16 } {
                'Desktop'
            }
            { $_ -in 8, 9, 10, 11, 12, 14, 18, 21, 31, 32 } {
                'Laptop'
            }
            { $_ -in 30 } { 'Tablet' }
            { $_ -in 17, 23 } { 'Server' }
            Default { "" }
        }

        if (-not $result) {
            Write-Log "Chassis type $chassisType is not mapped." -Level Error
        } elseif (
            (($env:COMPUTERNAME -like "*-DT-*") -and $($result -ne 'Desktop')) -or
            (($env:COMPUTERNAME -like "*-LT-*") -and $($result -ne 'Laptop')) -or
            (($env:COMPUTERNAME -like "*-TB-*") -and $($result -ne 'Tablet')) -or
            (($env:COMPUTERNAME -like "*-SV-*") -and $($result -ne 'Server'))
        ){
            Write-Log "Chassis type result $result doesn't match computer name $env:COMPUTERNAME." -Level Error
            $result = ""
        }

        return $result
    }

    function Get-GroupTag {
        if ($GroupTag) {
            $groupTags = $GroupTag -split "-"
        } else {
            $groupTags = @()
        }

        if (($groupTags -contains "Desktop") -or ($groupTags -contains "Laptop")) {
            Write-Log "Tags already contain either Desktop or Laptop"
        } elseif ($InputFile) {
            Write-Log "CSV Imported, skipping chassis check"
        } else {
            $chassisTag = Get-WUChassisType

            if ($chassisTag) {
                $groupTags += $chassisTag
            }
        }

        if ($AssignedUser) {
            $IsAdmin = $true
            $IsMSP = $IsMSP -or $AssignedUser.ToLower().StartsWith("ngt.")
        } else {
            $IsMSP = $IsMSP -or $env:COMPUTERNAME.StartsWith("NG-")
        }

        if (($groupTags -contains "Admin") -or ($groupTags -contains "Shared")) {
            Write-Log "Tags already contain either Admin or Shared"
        } elseif ($IsAdmin -and $AssignedUser) {
            $groupTags += "Admin"
        } elseif (-not $IsAdmin) {
            $groupTags += "Shared"
        } elseif ($IsAdmin) {
            Write-Log "-IsAdmin parameter is only supported with -AssignedUser switch" -Level Warning
        }

        if (($groupTags -contains "MSP") -or ($groupTags -contains "Client")) {
            Write-Log "Tags already contain either MSP or Client"
        } elseif ($IsMSP) {
            $groupTags += "MSP"
        } else {
            $groupTags += "Client"
        }

        return $groupTags -join "-"
    }

    function New-OutputDirectory {
        <#
        .SYNOPSIS
            Creates the output directory if it doesn't exist
        #>
        param(
            [string] $Path
        )

        try {
            if (Test-Path -Path $Path) {
                Write-Log "Output directory already exists: $Path"
            } else {
                Write-Log "Creating directory: $Path"
                New-Item -ItemType Directory -Path $Path -Force | Out-Null
                Write-Log "Directory created successfully" -Level Success
            }

            return $true
        } catch {
            Write-Log "Failed to create directory '$Path': $($_.Exception.Message)" -Level Error
            return $false
        }
    }

    if (New-OutputDirectory -Path $OutputPath) {
        Set-Content -Path $LogFilePath -Value "=== Autopilot Info Collection Started ===" -ErrorAction Stop
        Write-Log "========================================"
        Write-Log "Windows Autopilot Hardware ID Collection"
        Write-Log "========================================"
        Write-Log "Logging to: $LogFilePath"
        $canLog = $true
    } else {
        $canLog = $false
    }

    if ($AssignedUser -and $(-not ($AssignedUser -like "*@*.*"))) {
        Write-Log "Invalid Assigned user: $AssignedUser" -Level Warning
        $AssignedUser = ""
    }

    $groupTag = Get-GroupTag

    function Test-Administrator {
        $user = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal $user
        return $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
    }

    function Set-SecureTLS {
        <#
        .SYNOPSIS
            Configures secure TLS protocol for web requests
        #>
        $success = $false

        try {
            $ProtocolsSupported = [enum]::GetValues('Net.SecurityProtocolType')

            if (($ProtocolsSupported -contains 'Tls13') -and ($ProtocolsSupported -contains 'Tls12')) {
                Write-Log "Configuring TLS 1.3 and TLS 1.2"
                [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
                $success = $true
            } elseif ($ProtocolsSupported -contains 'Tls12') {
                Write-Log "Configuring TLS 1.2"
                [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                $success = $true
            } else {
                Write-Log "TLS 1.2 or higher is not supported on this system" -Level Error
            }
        } catch {
            Write-Log "Failed to configure TLS: $($_.Exception.Message)" -Level Error
        }

        return $success
    }

    function Install-AutopilotScript {
        <#
        .SYNOPSIS
            Installs or updates Get-WindowsAutopilotInfo
        #>
        $success = $false

        if ($ScriptName -and $ScriptVersion) {
            $hasScript = Get-InstalledScript -Name $ScriptName -RequiredVersion $ScriptVersion -ErrorAction SilentlyContinue
        } else {
            $hasScript = $false
        }

        if ($hasScript) {
            Write-Log "$ScriptName version $($hasScript.Version) is already installed"
            $success = $true
        } elseif ($ScriptName -and $ScriptVersion) {
            $currentPolicy = Get-ExecutionPolicy -Scope Process
            if ($currentPolicy -eq 'Restricted' -or $currentPolicy -eq 'AllSigned') {
                Write-Log "Temporarily setting execution policy to RemoteSigned for installation"
                Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
            }

            $hasNuGet = Get-PackageProvider -Name "NuGet" -ErrorAction SilentlyContinue
            if (-not $hasNuGet) {
                Write-Log "Installing NuGet..."
                Install-PackageProvider -Name "NuGet" -Force
            }

            $hasPSGallery = Get-PackageSource -Name "PSGallery" -ErrorAction SilentlyContinue
            if (-not $hasPSGallery) {
                Write-Log "Trusting PowerShell Gallery..."
                Set-PSRepository -Name "PSGallery" -InstallationPolicy Trusted
            }

            Write-Log "Installing $ScriptName from PowerShell Gallery..."
            Install-Script -Name $ScriptName -ErrorAction Stop -RequiredVersion $ScriptVersion -Force
            Write-Log "Successfully installed $ScriptName" -Level Success
            $success = $true
        } else {
            $success = $true
        }

        return $success
    }

    function Is-ScriptInPath {
        param(
            [Parameter(Mandatory = $true)]
            [string] $scriptsPath
        )

        return $env:Path -like "*$scriptsPath*"
    }

    function Add-ScriptsToPath {
        <#
        .SYNOPSIS
            Adds PowerShell Scripts directory to PATH if not already present
        #>
        param(
            [Parameter(Mandatory = $true)]
            [string] $scriptsPath
        )

        if (Is-ScriptInPath $scriptsPath) {
            Write-Log "PowerShell Scripts directory already in PATH"
        } else {
            Write-Log "Adding PowerShell Scripts directory to PATH"
            $env:Path += ";$scriptsPath"
        }
    }

    function New-AutopilotArgs {
        <#
        .SYNOPSIS
            Builds parameter array for Get-WindowsAutopilotInfo with optional device metadata
        #>
        param(
            [Parameter(Mandatory = $false)]
            [hashtable] $BaseParams
        )

        $params = if ($BaseParams) { $BaseParams.Clone() } else { @{} }
        $autopilotArgs = @()

        $optionalParams = @{
            'AppId' = $AppId
            'TenantId' = $AppTenantId
            'InputFile' = $InputFile
            'Online' = $Online
            'Delete' = $Delete
            'Append' = $Append
        }

        if ($Online -and $(-not $($Delete -or $Interactive))) {
            $optionalParams['Force'] = $true
        }

        if ($Online -and $(-not $Delete)) {
            # $optionalParams['newdevice'] = $true
            $optionalParams['AssignedComputerName'] = $AssignedComputerName
        }

        if (-not $Delete) {
            $optionalParams['AssignedUser'] = $AssignedUser
            $optionalParams['GroupTag'] = $groupTag
        }

        $optionalParams.GetEnumerator() | ForEach-Object {
            if (-not [string]::IsNullOrWhiteSpace($_.Value)) {
                $params[$_.Key] = $_.Value
            }
        }

        $params.GetEnumerator() | ForEach-Object {
            if ( [string]::IsNullOrWhiteSpace($_.Value) -or ($_.Value -eq $true)) {
                $autopilotArgs += "-$($_.Key)"
            } elseif ($_.Value -eq $false) {
                return
            } else {
                $autopilotArgs += "-$($_.Key) `"$($_.Value)`""
            }

            if ($($_.Key) -eq 'AppSecret') {
                Write-Log "Set AppSecret to xxxxxx..."
            } else {
                Write-Log "Set $($_.Key) to $($_.Value)"
            }
        }

        return $autopilotArgs
    }

    function Get-SecretFromKeyVault {
        <#
        .SYNOPSIS
            Retrieves a secret from Azure Key Vault
        #>
        param(
            [Parameter(Mandatory = $true)]
            [string] $VaultName,

            [Parameter(Mandatory = $true)]
            [string] $SecretName,

            [Parameter(Mandatory = $false)]
            [string] $tenantId,

            [Parameter(Mandatory = $false)]
            [string] $SubscriptionId
        )

        $secret = $false

        Write-Log "Retrieving secret '$SecretName' from Key Vault '$VaultName'..."
        $requiredModules = @("Az.Accounts", "Az.KeyVault")

        foreach ($module in $requiredModules) {
            if (Get-InstalledModule -Name $module -ErrorAction SilentlyContinue) {
                Write-Log "$module module found"
            } else {
                Write-Log "$module module not found. Installing..." -Level Warning
                Install-Module -Name $module -Repository PSGallery -Scope CurrentUser -Confirm:$false -Force
            }
        }

        Import-Module Az.Accounts -ErrorAction Stop
        Import-Module Az.KeyVault -ErrorAction Stop
        $context = Get-AzContext -ErrorAction SilentlyContinue

        if ($context) {
            Write-Log "Using existing Azure connection for account: $($context.Account)"

            if ($SubscriptionId -and $context.Subscription.Id -ne $SubscriptionId) {
                Write-Log "Switching to subscription: $SubscriptionId"
                Set-AzContext -SubscriptionId $SubscriptionId -ErrorAction Stop | Out-Null
            }
        } elseif ($Interactive) {
            Write-Log "Not connected to Azure. Connecting..."
            $connectParams = @{ ErrorAction = 'Stop' }

            if ($tenantId) {
                $connectParams['Tenant'] = $tenantId
                Write-Log "Connecting to tenant: $tenantId"
            }

            if ($SubscriptionId) {
                $connectParams['SubscriptionId'] = $SubscriptionId
                Write-Log "Connecting to subscription: $SubscriptionId"
            }

            Connect-AzAccount @connectParams | Out-Null
            Write-Log "Successfully connected to Azure" -Level Success
        } else {
            Write-Log "Non-interactive mode requires existing Azure authentication. Please run 'Connect-AzAccount' before executing this script, or use managed identity/service principal authentication." -Level Error
        }

        $secret = Get-AzKeyVaultSecret -VaultName $VaultName -Name $SecretName -AsPlainText -ErrorAction Stop

        if ($secret) {
            Write-Log "Successfully retrieved secret from Key Vault" -Level Success
        } elseif ($secret -eq $false) {
            Write-Log "Unable to connect to Key Vault '$VaultName'" -Level Error
        } else {
            Write-Log "Secret '$SecretName' not found in Key Vault '$VaultName'" -Level Error
        }

        return $secret
    }

    function Get-Session {
        param(
            [Parameter(Mandatory = $False, Position = 0)]
            [alias("DNSHostName", "ComputerName", "Computer")] [String] $Name = "localhost",

            [Parameter(Mandatory = $False)]
            [System.Management.Automation.PSCredential] $Credential = $null
        )

        try {
            if ($Name -eq "localhost") {
                $session = New-CimSession -ErrorAction SilentlyContinue
            } elseif ($Credential) {
                $session = New-CimSession -ComputerName $Name -Credential $Credential -ErrorAction SilentlyContinue
            } else {
                $session = New-CimSession -ComputerName $Name -ErrorAction SilentlyContinue
            }
        } catch {
            $session = $null
        }

        return $session
    }

    function Get-Serial {
        param(
            [Parameter(Mandatory = $False, Position = 0)]
            [Microsoft.Management.Infrastructure.CimSession] $session
        )

        if ($session) {
            $serial = (Get-CimInstance -CimSession $session -Class Win32_BIOS).SerialNumber
        } else {
            $serial = (Get-CimInstance -Class Win32_BIOS).SerialNumber
        }

        return $serial
    }

    function Get-ComputerInput {
        param(
            [Parameter(Mandatory = $False, Position = 0)]
            [alias("DNSHostName", "ComputerName", "Name")] [String] $computer = "localhost",

            [Parameter(Mandatory = $False)]
            [System.Management.Automation.PSCredential] $Credential = $null
        )

        $session = Get-Session $computer -Credential $Credential

        if ($session) {
            $serial = Get-Serial $session
            Write-Log "Checking details for $computer (${serial})..."
            $namespace = 'root/cimv2/mdm/dmmap'
            $filter = "InstanceID='Ext' AND ParentID='./DevDetail'"
            $devDetail = Get-CimInstance -CimSession $session -Namespace $namespace -Class MDM_DevDetail_Ext01 -Filter $filter
        } else {
            $devDetail = $null
        }

        if ($devDetail) {
            $input = New-Object psobject -Property @{
                "Device Serial Number" = $serial
                "Windows Product ID"   = ""
                "Hardware Hash"        = $devDetail.DeviceHardwareData
            }

            if ($groupTag) {
                Add-Member -InputObject $input -NotePropertyName "Group Tag" -NotePropertyValue $groupTag
            }

            if ($AssignedUser) {
                Add-Member -InputObject $input -NotePropertyName "Assigned User" -NotePropertyValue $AssignedUser
            }

            Write-Log "Gathered details for $computer (${serial})"
        } else {
            $input = $null
            Write-Log "Unable to retrieve device hash from $computer (${serial})" -Level Error
        }

        if ($session) { Remove-CimSession $session }
        return $input
    }

    function Get-HashCSV {
        param(
            [Parameter(Mandatory = $true, Position = 0)] $computers
        )

        Begin {
            $success = $true

            if ($Online) {
                $outputFile = ""
            } elseif ($InputFile) {
                $InputFileName = Split-Path $InputFile -Leaf
                $outputFile = Join-Path -Path $OutputPath -ChildPath $InputFileName
            } else {
                $serial = Get-Serial

                if ($serial) {
                    $outputFileName = "${serial}.csv"
                } else {
                    $outputFileName = "AutopilotHWID.csv"
                }

                $outputFile = Join-Path -Path $OutputPath -ChildPath $OutputFileName
            }

            if (-not $Append) {
                Remove-Item $outputFile -ErrorAction SilentlyContinue
            }
        }

        Process {
            if ($InputFile) {
                Write-Log "Re-exporting hardware information to CSV..."

                if ($computers[0].PSObject.Properties.Name -contains "Group Tag") {
                    Write-Log "Replacing existing tag ${groupTag}..."
                } else {
                    Write-Log "Adding new tag ${groupTag}..."
                }

                foreach ($row in $computers) {
                    $row | Add-Member -MemberType NoteProperty -Name "Group Tag" -Value $groupTag -Force
                }

                if ($Online) {
                    $success = Import-AutopilotData $computers
                } elseif ($Append) {
                    Write-Log "Append with InputFile not yet implemented!" -Level Error
                    $success = $false
                } else {
                    $computers | Export-Csv -Path $outputFile -NoTypeInformation
                }
            } else {
                $objects = @("Device Serial Number", "Windows Product ID", "Hardware Hash")

                if ($AssignedUser) {
                    $objects += "Assigned User"
                }

                if ($groupTag) {
                    $objects += "Group Tag"
                }

                $computers | Select-Object @$objects | Export-Csv -Path $outputFile -NoTypeInformation
                #$data | ConvertTo-Csv -NoTypeInformation | ForEach-Object { $_ -replace '"', '' } | Out-File $outputFile
            }
        }

        End {
            if ($success -and $outputFile) {
                $success = $(Test-Path -Path $outputFile) -and $(Get-Item $outputFile).Length
            }

            return @{success = $success; outputFile = $outputFile}
        }
    }

    function Set-EffectiveAppSecret {
        if ($KeyVaultName -and $SecretName) {
            Write-Log "Using Azure Key Vault for secret retrieval"

            $kvParams = @{
                VaultName  = $KeyVaultName
                SecretName = $SecretName
                tenantId = $AppTenantId
                SubscriptionId = $SubscriptionId
            }

            $effectiveAppSecret = Get-SecretFromKeyVault @kvParams
        } else {
            $effectiveAppSecret = $AppSecret
        }

        return $effectiveAppSecret
    }

    Function Connect-ToGraph {
        <#
        .SYNOPSIS
        Authenticates to the Graph API via the Microsoft.Graph.Authentication module.

        .DESCRIPTION
        The Connect-ToGraph cmdlet is a wrapper cmdlet that helps authenticate to the Intune Graph API using the Microsoft.Graph.Authentication module. It leverages an Entra app ID and app secret for authentication or user-based auth.

        .PARAMETER tenantId
        Specifies the tenant (e.g. contoso.onmicrosoft.com) to which to authenticate.

        .PARAMETER secret
        Specifies the Entra app secret corresponding to the app ID that will be used to authenticate.

        .PARAMETER Scopes
        Specifies the user scopes for interactive authentication.

        .EXAMPLE
        Connect-ToGraph -tenantIdId $tenantID -secret $secret

        -#>
        [cmdletbinding()]
        param
        (
            [Parameter(Mandatory = $false)] [string] $tenantId,
            [Parameter(Mandatory = $false)] [string] $secret,
            [Parameter(Mandatory = $false)] [string] $scopes
        )

        Process {
            $provider = Get-PackageProvider NuGet -ErrorAction Ignore
            if (-not $provider) {
                Write-Log "Installing provider NuGet"
                Find-PackageProvider -Name NuGet -ForceBootstrap -IncludeDependencies
            }

            $module = Import-Module microsoft.graph.authentication -PassThru -ErrorAction Ignore

            if (-not $module) {
                Write-Log "Trusting PowerShell Gallery..."
                Set-PSRepository -Name "PSGallery" -InstallationPolicy Trusted
                Write-Log "Installing module microsoft.graph.authentication"
                Install-Module microsoft.graph.authentication -Force -ErrorAction Ignore -MaximumVersion 2.32.9
            }

            $version = Get-Module microsoft.graph.authentication | Select-Object -ExpandProperty Version
            $majorVersion = if ($version) { $version.major } else { 0 }
            $graph = $null

            if ($AppId -and $tenantId) {
                Write-Log "AppId and tenantId supplied"

                $body = @{
                    grant_type    = "client_credentials";
                    client_id     = $AppId;
                    client_secret = $secret;
                    scope         = "https://graph.microsoft.com/.default";
                }

                $response = Invoke-RestMethod -Method Post -Uri "https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/token" -Body $body
                $accessToken = try { $response.access_token } catch { "" }
                $secureAccessToken = $accessToken

                if ($accessToken -and $($majorVersion -eq 2)) {
                    Write-Log "Version 2 module detected"
                    $secureAccessToken = ConvertTo-SecureString -String $accessToken -AsPlainText -Force
                } elseif ($accessToken -and $($majorVersion -eq 1)) {
                    Write-Log "Version 1 module detected"
                    Select-MgProfile -Name Beta
                    $secureAccessToken = $accessToken
                } elseif ($majorVersion) {
                    Write-Log "Unknown module version $majorVersion detected!" -Level Error
                } elseif ($accessToken) {
                    Write-Log "No module version detected!" -Level Error
                } else {
                    Write-Log "accessToken is empty!" -Level Error
                }

                if ($secureAccessToken) {
                    $graph = Connect-MgGraph -AccessToken $secureAccessToken
                    Write-Log "Connected to Intune tenant $tenantId using app-based authentication (Entra authentication not supported)"
                } else {
                    Write-Log "secureAccessToken is empty!" -Level Error
                }
            }
            else {
                if (-not $($AppId -or $tenantId)) {
                    Write-Log "AppId and tenantId were NOT supplied"
                } elseif ($AppId) {
                    Write-Log "tenantId NOT supplied"
                } else {
                    Write-Log "AppId NOT supplied"
                }

                if ($version -eq 2) {
                    Write-Log "Version 2 module detected"
                }
                else {
                    Write-Log "Version 1 Module Detected"
                    Select-MgProfile -Name Beta
                }

                $graph = Connect-MgGraph -Scopes $scopes
                Write-Log "Connected to Intune tenant"
            }

            return $graph
        }
    }

    function Test-RequiredScopes {
        [CmdletBinding()]
        param (
            [Parameter(Mandatory = $false, ValueFromPipeline = $true)]
            [Alias('Permission')]
            [string[]] $Scope
        )

        process {
            $result = $false
            $mgContext = Get-MgContext

            if ($mgContext -and $Scope) {
                $currentScopes = $mgContext.Scopes
                # If I have ReadWrite scope, I also have Read scope
                $newScopes = $currentScopes.Where({ $_ -like '*ReadWrite*' }) | ForEach-Object { $_.Replace('ReadWrite', 'Read') }
                $allScopes = $currentScopes + $newScopes

                [string[]] $missingScopes = Compare-Object $Scope -DifferenceObject $allScopes |
                    Where-Object SideIndicator -EQ '<=' |
                    Select-Object -ExpandProperty InputObject

                if ($missingScopes) {
                    $scopes = $missingScopes -join ', '
                    Write-Log "Additional scope(s) needed: $scopes" -Level Error
                } else {
                    $result = $mgContext
                }
            } elseif (-not $mgContext) {
                Write-Log "Authentication needed, call Connect-MgGraph" -Level Error
            }

            return $result
        }
    }

    Function Get-AutopilotDevice() {
        <#
        .SYNOPSIS
        Gets devices currently registered with Windows Autopilot.

        .DESCRIPTION
        The Get-AutopilotDevice cmdlet retrieves either the full list of devices registered with Windows Autopilot for the current Entra tenant, or a specific device if the ID of the device is specified.

        .PARAMETER id
        Optionally specifies the ID (GUID) for a specific Windows Autopilot device (which is typically returned after importing a new device)

        .PARAMETER serial
        Optionally specifies the serial number of the specific Windows Autopilot device to retrieve

        .PARAMETER expand
        Expand the properties of the device to include the Autopilot profile information

        .EXAMPLE
        Get a list of all devices registered with Windows Autopilot

        Get-AutopilotDevice
        #>
        [cmdletbinding()]
        param
        (
            [Parameter(Mandatory = $false, ValueFromPipelineByPropertyName = $true)] $id,
            [Parameter(Mandatory = $false)] $serial,
            [Parameter(Mandatory = $false)] [Switch] $expand = $false
        )

        Begin {
            $devices = $null
            $serialhasspaces = $false
            $graphApiVersion = "beta"
            $Resource = "deviceManagement/windowsAutopilotDeviceIdentities"
            $uri = "https://graph.microsoft.com/${graphApiVersion}/$Resource"
            $scopes = 'DeviceManagementServiceConfig.Read.All'
            $response = $null
            $mgContext = Test-RequiredScopes $scopes -ErrorAction Stop
            $effectiveAppSecret = Set-EffectiveAppSecret

            if ($id -and $expand) {
                $uri += "/$($id)?`$expand=deploymentProfile,intendedDeploymentProfile"
            } elseif ($id) {
                $uri += "/$id"
            } elseif ($serial) {
                $serialelements = $serial.Split(" ")
                $serialhasspaces = $serialelements.Count -gt 1

                if ($serialhasspaces) {
                    $uri += "?`$filter=contains(serialNumber,'$($serialelements[0])')"
                } else {
                    $encoded = [uri]::EscapeDataString($serial)
                    $uri += "?`$filter=contains(serialNumber,'$encoded')"
                }
            } else {
                Write-Log "Loading all objects. This can take a while on large tenants..."
            }
        }

        Process {
            if ($mgContext) {
                Write-Log "Required scopes already acquired."
            } elseif ($AppId -and $effectiveAppSecret) {
                $mgContext = Connect-ToGraph -secret $effectiveAppSecret -tenantId $AppTenantId
            } else {
                $mgContext = Connect-ToGraph -scope $scopes
            }

            if (!$mgContext) {
                Write-Log "Microsoft Graph authentication failed!" -Level Error
            } elseif (!(Test-RequiredScopes $scopes -ErrorAction Stop)) {
                $missingScopes = $true
                Write-Log "Missing required scopes!" -Level Error
            } else {
                Write-Verbose "GET $uri"

                try {
                    $response = Invoke-MgGraphRequest -Uri $uri -Method Get -OutputType PSObject -ErrorAction Stop
                } catch {
                    Write-Log ("Error in {0} at line {1}" -f $MyInvocation.MyCommand, $MyInvocation.ScriptLineNumber) -Level Error
                    Write-Log $uri
                    Write-Log $_.Exception.Message -Level Error
                    $response = $null
                }
            }

            if ($id -and $response) {
                $devices = $response
            } elseif ($response) {
                $devices = try { $response.value } catch { $null }

                if ($devices -and $serialhasspaces) {
                    $devices = $devices | Where-Object { $_.serialNumber -eq "$serial" }
                }

                $nextLink = try { $response."@odata.nextLink" } catch { $null }

                while ($nextLink) {
                    try {
                        $devicesResponse = Invoke-MgGraphRequest -Uri $nextLink -Method Get -OutputType PSObject -ErrorAction Stop
                    } catch {
                        Write-Log ("Error in {0} at line {1}" -f $MyInvocation.MyCommand, $MyInvocation.ScriptLineNumber) -Level Error
                        Write-Log $uri
                        Write-Log $_.Exception.Message -Level Error
                        $devicesResponse = $null
                    }

                    $nextLink = try { $devicesResponse."@odata.nextLink" } catch { $null }

                    if ($serialhasspaces) {
                        $devices += $devicesResponse.value | Where-Object { $_.serialNumber -eq "$($serial)" }
                    }
                    else {
                        $devices += $devicesResponse.value
                    }
                }

                if ($expand) {
                    $devices = $devices | Get-AutopilotDevice -expand
                }
            }
        }

        End {
            return $devices
        }
    }

    Function Get-AutopilotImportedDevice() {
        <#
        .SYNOPSIS
        Gets information about devices being imported into Windows Autopilot.

        .DESCRIPTION
        The Get-AutopilotImportedDevice cmdlet retrieves either the full list of devices being imported into Windows Autopilot for the current Entra tenant, or information for a specific device if the ID of the device is specified. Once the import is complete, the information instance is expected to be deleted.

        .PARAMETER id
        Optionally specifies the ID (GUID) for a specific Windows Autopilot device being imported.

        .EXAMPLE
        Get a list of all devices being imported into Windows Autopilot for the current Entra tenant.

        Get-AutopilotImportedDevice
        #>
        [cmdletbinding()]
        param
        (
            [Parameter(Mandatory = $false)] $id = $null,
            [Parameter(Mandatory = $false)] $serial
        )

        $devices = $null
        $serialhasspaces = $false
        $graphApiVersion = "beta"
        $Resource = "deviceManagement/importedWindowsAutopilotDeviceIdentities"
        $uri = "https://graph.microsoft.com/${graphApiVersion}/$Resource"
        $scopes = 'DeviceManagementServiceConfig.Read.All'
        $response = $null
        $mgContext = Test-RequiredScopes $scopes -ErrorAction Stop
        $effectiveAppSecret = Set-EffectiveAppSecret

        if ($id) {
            $uri += "/$id"
        } elseif ($serial) {
            $serialelements = $serial.Split(" ")
            $serialhasspaces = $serialelements.Count -gt 1

            if ($serialhasspaces) {
                $uri += "?`$filter=contains(serialNumber,'$($serialelements[0])')"
            } else {
                $encoded = [uri]::EscapeDataString($serial)
                $uri += "?`$filter=contains(serialNumber,'$encoded')"
            }
        } else {
            Write-Log "Loading all objects. This can take a while on large tenants..."
        }

        if ($mgContext) {
            Write-Log "Required scopes already acquired."
        } elseif ($AppId -and $effectiveAppSecret) {
            $mgContext = Connect-ToGraph -secret $effectiveAppSecret -tenantId $AppTenantId
        } else {
            $mgContext = Connect-ToGraph -scope $scopes
        }

        if (!$mgContext) {
            Write-Log "Microsoft Graph authentication failed!" -Level Error
        } elseif (!(Test-RequiredScopes $scopes -ErrorAction Stop)) {
            $missingScopes = $true
            Write-Log "Missing required scopes!" -Level Error
        } else {
            Write-Verbose "GET $uri"

            try {
                $response = Invoke-MgGraphRequest -Uri $uri -Method Get -OutputType PSObject -ErrorAction Stop
            } catch {
                Write-Log ("Error in {0} at line {1}" -f $MyInvocation.MyCommand, $MyInvocation.ScriptLineNumber) -Level Error
                Write-Log $uri
                Write-Log $_.Exception.Message -Level Error
                $response = $null
            }
        }

        if ($response -and $id) {
            $devices = $response
        } elseif ($response) {
            $devices = try { $response.value } catch { $null }

            if ($devices -and $serialhasspaces) {
                $devices = $devices | Where-Object { $_.serialNumber -eq "$serial" }
            }

            $nextLink = try { $response."@odata.nextLink" } catch { $null }

            while ($nextLink) {
                try {
                    $devicesResponse = Invoke-MgGraphRequest -Uri $nextLink -Method Get -OutputType PSObject -ErrorAction Stop
                } catch {
                    Write-Log ("Error in {0} at line {1}" -f $MyInvocation.MyCommand, $MyInvocation.ScriptLineNumber) -Level Error
                    Write-Log $_.Exception.Message -Level Error
                    $devicesResponse = $null
                }

                $nextLink = try { $devicesResponse."@odata.nextLink" } catch { $null }

                if ($serialhasspaces) {
                    $devices += $devicesResponse.value | Where-Object { $_.serialNumber -eq "$($serial)" }
                }
                else {
                    $devices += $devicesResponse.value
                }
            }
        }

        return $devices
    }

    Function Set-AutopilotDevice() {
        <#
        .SYNOPSIS
        Updates settings on an Autopilot device.

        .DESCRIPTION
        The Set-AutopilotDevice cmdlet can be used to change the updatable properties on a Windows Autopilot device object.

        .PARAMETER id
        The Windows Autopilot device id (mandatory).

        .PARAMETER userPrincipalName
        The user principal name.

        .PARAMETER addressibleUserName
        The name to display during Windows Autopilot enrollment. If specified, the userPrincipalName must also be specified.

        .PARAMETER displayName
        The name (computer name) to be assigned to the device when it is deployed via Windows Autopilot. This is presently only supported with Entra Join scenarios. Note that names should not exceed 15 characters. After setting the name, you need to initiate a sync (Invoke-AutopilotSync) in order to see the name in the Intune object.

        .PARAMETER groupTag
        The group tag value to set for the device.

        .EXAMPLE
        Assign a user and a name to display during enrollment to a Windows Autopilot device.

        Set-AutopilotDevice -id $id -userPrincipalName $userPrincipalName -addressableUserName "John Doe" -displayName "CONTOSO-0001" -groupTag "Testing"
        #>
        [cmdletbinding()]
        param
        (
            [Parameter(Mandatory = $true, ValueFromPipelineByPropertyName = $True)] $id,
            [Parameter(ParameterSetName = "Prop")] $userPrincipalName = $null,
            [Parameter(ParameterSetName = "Prop")] $addressableUserName = $null,
            [Parameter(ParameterSetName = "Prop")][Alias("ComputerName", "CN", "MachineName")] $displayName = $null,
            [Parameter(ParameterSetName = "Prop")] $groupTag = $null
        )

        Process {
            $graphApiVersion = "beta"
            $Resource = "deviceManagement/windowsAutopilotDeviceIdentities"
            $uri = "https://graph.microsoft.com/${graphApiVersion}/${Resource}/${id}/UpdateDeviceProperties"
            $json = @{}

            if ($PSBoundParameters.ContainsKey('userPrincipalName')) {
                $json['userPrincipalName'] = $userPrincipalName
            }

            if ($PSBoundParameters.ContainsKey('addressableUserName')) {
                $json['addressableUserName'] = $addressableUserName
            }

            if ($PSBoundParameters.ContainsKey('displayName')) {
                $json['displayName'] = $displayName
            }

            if ($PSBoundParameters.ContainsKey('groupTag')) {
                $json['groupTag'] = $groupTag
            }

            $json = $json | ConvertTo-Json

            try {
                Invoke-MgGraphRequest -Uri $uri -Method POST -Body $json -ContentType "application/json" -OutputType PSObject
                $success = $true
            }
            catch {
                Write-Log $_.Exception -Level Error
                $success = $false
            }

            return $success
        }
    }


    Function Add-AutopilotImportedDevice() {
        <#
        .SYNOPSIS
        Adds a new device to Windows Autopilot.

        .DESCRIPTION
        The Add-AutopilotImportedDevice cmdlet adds the specified device to Windows Autopilot for the current Entra tenant. Note that a status object is returned when this cmdlet completes; the actual import process is performed as a background batch process by the Microsoft Intune service.

        .PARAMETER serialNumber
        The hardware serial number of the device being added (mandatory).

        .PARAMETER hardwareIdentifier
        The hardware hash (4K string) that uniquely identifies the device.

        .PARAMETER groupTag
        An optional identifier or tag that can be associated with this device, useful for grouping devices using Entra dynamic groups.

        .PARAMETER displayName
        The optional name (computer name) to be assigned to the device when it is deployed via Windows Autopilot. This is presently only supported with Entra Join scenarios. Note that names should not exceed 15 characters. After setting the name, you need to initiate a sync (Invoke-AutopilotSync) in order to see the name in the Intune object.

        .PARAMETER assignedUser
        The optional user UPN to be assigned to the device. Note that no validation is done on the UPN specified.

        .EXAMPLE
        Add a new device to Windows Autopilot for the current Entra tenant.

        Add-AutopilotImportedDevice -serialNumber $serial -hardwareIdentifier $hash -groupTag "Kiosk" -assignedUser "anna@contoso.com"
        #>
        [cmdletbinding()]
        param
        (
            [Parameter(Mandatory = $true)] $serialNumber,
            [Parameter(Mandatory = $true)] $hardwareIdentifier,
            [Parameter(Mandatory = $false)] [Alias("orderIdentifier")] $groupTag = "",
            [Parameter(ParameterSetName = "Prop2")][Alias("UPN")] $assignedUser = ""
        )

        $graphApiVersion = "beta"
        $Resource = "deviceManagement/importedWindowsAutopilotDeviceIdentities"
        $uri = "https://graph.microsoft.com/${graphApiVersion}/$Resource"
        $json = @{
            "@odata.type" = "#microsoft.graph.importedWindowsAutopilotDeviceIdentity";
            "groupTag" = "$groupTag";
            "serialNumber" = "$serialNumber";
            "productKey" = "";
            "hardwareIdentifier" = "$hardwareIdentifier";
            "assignedUserPrincipalName" = "$assignedUser"
            "state" = @{
                "@odata.type" = "microsoft.graph.importedWindowsAutopilotDeviceIdentityState";
                "deviceImportStatus" = "pending";
                "deviceRegistrationId" = "";
                "deviceErrorCode" = 0;
                "deviceErrorName" = ""
            }
        } | ConvertTo-Json

        Write-Verbose "POST $uri`n$json"

        try {
            return Invoke-MgGraphRequest -Uri $uri -Method Post -Body $json -ContentType "application/json" -OutputType PSObject
        }
        catch {
            Write-Error $_.Exception
        }
    }

    Function Remove-AutopilotImportedDevice() {
        <#
        .SYNOPSIS
        Removes the status information for a device being imported into Windows Autopilot.

        .DESCRIPTION
        The Remove-AutopilotImportedDevice cmdlet cleans up the status information about a new device being imported into Windows Autopilot. This should be done regardless of whether the import was successful or not.

        .PARAMETER id
        The ID (GUID) of the imported device status information to be removed (mandatory).

        .EXAMPLE
        Remove the status information for a specified device.

        Remove-AutopilotImportedDevice -id $id
        #>
        [cmdletbinding()]
        param
        (
            [Parameter(Mandatory = $true, ValueFromPipelineByPropertyName = $True)] $id
        )

        Process {
            $graphApiVersion = "beta"
            $Resource = "deviceManagement/importedWindowsAutopilotDeviceIdentities"
            $uri = "https://graph.microsoft.com/${graphApiVersion}/${Resource}/$id"
            Write-Verbose "DELETE $uri"

            try {
                return Invoke-MgGraphRequest -Uri $uri -Method DELETE -OutputType PSObject
            }
            catch {
                Write-Error $_.Exception
            }
        }
    }

    Function Invoke-AutopilotSync() {
        <#
        .SYNOPSIS
        Initiates a synchronization of Windows Autopilot devices between the Autopilot deployment service and Intune.

        .DESCRIPTION
        The Invoke-AutopilotSync cmdlet initiates a synchronization between the Autopilot deployment service and Intune.
        This can be done after importing new devices, to ensure that they appear in Intune in the list of registered
        Autopilot devices. See https://developer.microsoft.com/en-us/graph/docs/api-reference/beta/api/intune_enrollment_windowsautopilotsettings_sync
        for more information.

        .EXAMPLE
        Initiate a synchronization.

        Invoke-AutopilotSync
        #>
        [cmdletbinding()]
        param()
        $graphApiVersion = "beta"
        $Resource = "deviceManagement/windowsAutopilotSettings/sync"
        $uri = "https://graph.microsoft.com/${graphApiVersion}/$Resource"

        Write-Verbose "POST $uri"

        try {
            return Invoke-MgGraphRequest -Uri $uri -Method Post -OutputType PSObject
        }
        catch {
            Write-Error $_.Exception
        }
    }

    function Import-AutopilotData {
         <#
        .SYNOPSIS
            Adds a batch of new devices into Windows Autopilot.

        .DESCRIPTION
            The Import-AutopilotData cmdlet processes a list of new devices It is a convenient wrapper to handle the details.
            After the devices have been added, the cmdlet will continue to check the status of the import process. Once all devices
            have been processed (successfully or not) the cmdlet will complete. This can take several minutes, as the devices are
            processed by Intune as a background batch process.

        .EXAMPLE
            Add a batch of devices to Windows Autopilot for the current Entra tenant.

            $computers = Import-Csv -Path $InputFile
            Import-AutopilotData $computers
        #>
        [cmdletbinding()]
        param
        (
            [Parameter(Mandatory = $true, Position = 0)] $computers
        )

        $importStart = Get-Date
        $queued = @()
        $successful = @()
        $synced = @()
        $computerCount = $computers.Length
        $devices = if ($computerCount -ge 10) { Get-AutopilotDevice } else { @() }

        if ($computerCount -gt 0) {
            Write-Log "$computerCount devices loaded."
        }

        $computers | ForEach-Object {
            $serial = $_.'Device Serial Number'

            if ($devices) {
                $device = $devices | Where-Object { $_.serialNumber -eq "$serial" }
            } else {
                $device = Get-AutopilotDevice -serial $serial
            }

            if ($device) {
                $lastSeen = $device.lastContactedDateTime
                Write-Log "$($device.model) $serial already exists in Autopilot."

                if ($lastSeen.Year -gt 1) {
                    Write-Log ("  last checked-in {0}" -f $lastSeen.ToString("dddd yyyy-MM-dd hh:mm tt"))
                }

                if ($UpdateExisting) {
                    Write-Log "  updating group tag..."
                    $success = Set-AutopilotDevice -id $device.Id -groupTag $groupTag

                    if ($success) {
                        $successful += $device
                        Write-Log "Update group tag to $groupTag." -Level Success
                    } else {
                        Write-Log "Unable to update group tag." -Level Error
                    }

                } else {
                    Write-Log "  skipping..."
                }
            } else {
                Write-Log "Adding $serial..."
                $hash = $_.'Hardware Hash'
                $tag = ""
                $user = ""

                if ($_.PSObject.Properties.Name -contains 'Group Tag') {
                    $tag = $_.'Group Tag'
                }

                if ($_.PSObject.Properties.Name -contains 'Assigned User') {
                    $user = $_.'Assigned User'
                }

                $queued += Add-AutopilotImportedDevice -serialNumber $serial -hardwareIdentifier $hash -groupTag $tag -assignedUser $user
            }
        }

        $queueCount = $queued.Length
        $successCount = $successful.Length
        $canImport = $queueCount -gt 0

        if ($canImport) {
            Write-Log "$queueCount devices queued successfully." -Level Success

            while ($true) {
                $processing = @()

                $queued | ForEach-Object {
                    $device = Get-AutopilotImportedDevice -id $_.id
                    $status = $null

                    if ($device) {
                        $status = $device.state.deviceImportStatus
                    }

                    if ($status -eq "unknown") {
                        $processing += $device
                    } elseif ($status) {
                        $exitCode = $device.state.deviceErrorCode

                        if ($exitCode -eq 0) {
                            Write-Log "$($device.serialNumber): status=$status" -Level Success

                            if ($status -eq "complete") {
                                $successful += $device
                            }
                        } else {
                            $error = $device.state.deviceErrorName
                            Write-Log "$($device.serialNumber): status=${status}; exit code=${exitCode}; error=${error}" -Level Error
                        }
                    }
                }

                $processingCount = $processing.Length

                if ($processingCount -gt 0) {
                    Write-Log "Waiting for $processingCount of $queueCount to be imported"
                    Start-Sleep 15
                } else {
                    break
                }
            }

            $importDuration = (Get-Date) - $importStart
            $importSeconds = [Math]::Ceiling($importDuration.TotalSeconds)
            $successCount = $successful.Length
            $canSync = $successCount -gt 0
        } else {
            Write-Log "No devices to import"
            $canSync = $successCount -gt 0
        }

        if ($canSync) {
            Write-Log "$successCount devices imported successfully. Elapsed time to complete import: $importSeconds seconds." -Level Success
            $syncStart = Get-Date

            while ($true) {
                $syncing = @()
                $successful | ForEach-Object {
                    $device = $_

                    try {
                        $id = $_.state.deviceRegistrationId
                        $device = Get-AutopilotDevice -id $id
                    } catch {
                        Write-Log "Using cached device result"
                    }

                    if ($device) {
                        $synced += $device
                    } else {
                        $syncing += $device
                    }
                }

                $syncingCount = $syncing.Length

                if ($syncingCount -gt 0) {
                    Write-Log "Waiting for $syncingCount of $successCount to sync"
                    Start-Sleep 10
                } else {
                    break
                }
            }

            $syncDuration = (Get-Date) - $syncStart
            $syncSeconds = [Math]::Ceiling($syncDuration.TotalSeconds)
            $syncedCount = $synced.Length
            $canRefresh = $syncedCount -gt 0
        } else {
            Write-Log "No devices to sync"
            $canRefresh = $false
        }

        if ($canRefresh) {
            Write-Log "$syncedCount devices synced. Elapsed time to complete sync: $syncSeconds seconds"  -Level Success

            if ($CleanupAutopilot) {
                $successful | ForEach-Object { Remove-AutopilotImportedDevice -id $_.id }
            }

            try {
                Invoke-AutopilotSync -ErrorAction Stop
            } catch {
                Write-Log "Unable to refresh Autopilot" -Level Warning
            }
        } else {
            Write-Log "No devices to refresh"
        }

        $success = $false

        if ($canRefresh) {
            $success = $true
        } elseif ($canSync) {
            Write-Log "$successCount devices imported, but none synced." -Level Error
        } elseif ($canImport) {
            Write-Log "$queueCount devices queued, but none imported." -Level Error
        } elseif ($computerCount) {
            $success = $true
            Write-Log "$computerCount devices loaded, but none queued." -Level Warning
            Write-Log "If this is unexpected, try again with the -UpdateExisting flag." -Level Warning
        } else {
            Write-Log "No devices loaded." -Level Error
        }

        return $success
    }

    function Test-TpmVersion {
        <#
        .SYNOPSIS
        Checks if TPM 2.0 is present and ready on the system.

        .DESCRIPTION
        Verifies that TPM 2.0+ is available, present, and ready for use.
        Returns $true if TPM 2.0+ is available, $false otherwise.
        Displays instructions if TPM needs to be enabled.

        .EXAMPLE
        if (Test-TpmVersion) {
            Write-Host "TPM 2.0 is available and ready"
        }
        #>
        param
        (
            [Parameter(Mandatory = $false, Position = 0)]
            [Switch] $tpmOnly
        )

        $success = $false
        $showInstructions = $false
        $tpmWmi = $null
        $tpm = $null
        $parallels = $false

        try {
            $tpm = Get-Tpm -ErrorAction Stop
        } catch {
            $bufferTooSmall = 'A specified output buffer is too small. (Exception from HRESULT: 0x80284005)'
            $parallels = $_.Exception.Message -eq $bufferTooSmall
            Write-Log "Error checking TPM status via Get-Tpm: $_" -Level Error
        }

        try {
            $tpmWmi = Get-WmiObject -Class Win32_Tpm -Namespace root\CIMV2\Security\MicrosoftTpm -ErrorAction Stop
        } catch {
            Write-Log "Error checking TPM status via Get-WmiObject: $_" -Level Error
        }

        $versions = if ($tpmWmi) { $tpmWmi.SpecVersion.Split(",") } else { @() }
        $versionMatch = $versions | ForEach-Object {$_.trim().StartsWith("2")} | Where-Object { $_ } | Select-Object -First 1

        if ($tpm) {
            $tpmPresent = $tpm.TpmPresent
            $tpmReady = $tpm.TpmReady
            $autoProvisioning = $tpm.AutoProvisioning -eq 'Enabled'
        } elseif ($parallels) {
            $tpmPresent = $tpmWmi -and $($tpmWmi.SpecVersion -ne "Not Supported")
            $tpmReady = $autoProvisioning = $versionMatch
        } else {
            $tpmPresent = $tpmReady = $autoProvisioning = $false
        }

        if (-not $tpmPresent) {
            Write-Log "TPM is not detected" -Level Warning
        } elseif ($tpmOnly) {
            $success = $true
        } elseif ($versionMatch) {
            Write-Log "TPM 2.0 detected with manufacturer $($tpmWmi.ManufacturerIdTxt)" -Level Success

            if ($tpmReady -and $autoProvisioning) {
                Write-Log "TPM 2.0 is ready and auto provisioning is enabled" -Level Success
                $success = $true
            } elseif ($tpmReady) {
                Write-Log "TPM 2.0 is ready, but auto provisioning is not enabled" -Level Success
                $success = $true
            } elseif ($tpmWmi.IsActivated ) {
                Write-Log "TPM 2.0 is activated but not ready" -Level Warning
                $showInstructions = $true
            } elseif ($tpmWmi.IsEnabled) {
                Write-Log "TPM 2.0 is enabled but not activated" -Level Warning
                $showInstructions = $true
            } else {
                Write-Log "TPM 2.0 is present but not enabled" -Level Warning
                $showInstructions = $true
            }
        } elseif ($tpmWmi) {
            Write-Log "TPM version $($tpmWmi.SpecVersion) detected, and is missing v2.0+" -Level Warning
        } else {
            Write-Log "TPM detected, but unable to determine the version." -Level Warning
        }

        if ($showInstructions) {
            Show-TpmEnableInstructions
        }

        return $success
    }

    function Show-TpmEnableInstructions {
        Write-Log "`n============================"
        Write-Log "HOW TO ENABLE TPM IN BIOS/UEFI"
        Write-Log "=============================="

        Write-Log "`nTo enable TPM, access your UEFI BIOS (PC firmware) settings:"

        Write-Log "`n1. Via Windows Settings:"
        Write-Log "   Settings > Update & Security > Recovery > Restart now"

        Write-Log "`n2. From the restart screen:"
        Write-Log "   Troubleshoot > Advanced options > UEFI Firmware Settings > Restart"

        Write-Log "`n3. In UEFI BIOS, look for TPM settings:"
        Write-Log "   - Usually found in: Advanced, Security, or Trusted Computing menus"
        Write-Log "   - May be labeled as:"
        Write-Log "     * Security Device"
        Write-Log "     * Security Device Support"
        Write-Log "     * TPM State"
        Write-Log "     * AMD fTPM switch / AMD PSP fTPM"
        Write-Log "     * Intel PTT / Intel Platform Trust Technology"

        Write-Log "`n4. Enable the TPM option and save changes"

        Write-Log "`nNote: After enabling TPM, restart and run this check again."
        Write-Log "========================================`n"
    }

    $success = $false
    $canProcess = $false
    $exitCode = 1

    if (-not $canLog) {
        Write-Warning "Failed to create output directory"
    } elseif (-not $(Test-Administrator)) {
        Write-Log "This script requires Administrator privileges. Please run PowerShell as Administrator." -Level Warning
    } elseif (-not $(Test-TpmVersion $true)) {
        Write-Log "This script requires TPM v2.0." -Level Warning
        Write-Log "To enroll the deviceis in Intune, you must wipe it with a USB drive and Entra ID join it."
    } elseif (-not $(Test-TpmVersion)) {
        Write-Log "This script requires TPM be available and ready." -Level Warning
    } elseif (-not $(Set-SecureTLS)) {
        Write-Log "This script requires SecureTLS." -Level Warning
    } elseif (Install-AutopilotScript) {
        $canProcess = $true
        $useScript = $ScriptName -and $ScriptVersion

        if ($useScript) {
            $scriptsPath = Get-InstalledScript -Name $ScriptName | Select-Object -ExpandProperty InstalledLocation
            $scriptPath = Join-Path $scriptsPath "${ScriptName}.ps1"
            $computers = $null
        } else {
            $scriptPath = ""
            $computers = @()
            $provider = Get-PackageProvider NuGet -ErrorAction Ignore

            if (-not $provider) {
                Write-Log "Installing provider NuGet"
                Find-PackageProvider -Name NuGet -ForceBootstrap -IncludeDependencies
            }

            $effectiveAppSecret = Set-EffectiveAppSecret

            if ($AppId -and $effectiveAppSecret) {
                Connect-ToGraph -secret $effectiveAppSecret -tenantId $AppTenantId | Out-Null
            } elseif ($interactive) {
                $scopes = "Device.ReadWrite.All", "DeviceManagementManagedDevices.ReadWrite.All", "DeviceManagementServiceConfig.ReadWrite.All", "DeviceManagementScripts.ReadWrite.All"
                Connect-ToGraph -scopes @$scopes
            } else {
                Write-Log "AppId and effectiveAppSecret not set" -Level Warning
            }
        }

        $p = $null
        $outputFile = ""
        $errors = ""
        $output = ""
        $powershell = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    }
}

Process {
    if ($canProcess) {
        if ($InputFile) {
            $computers = Import-Csv -Path $InputFile
        } else {
            foreach ($computer in $Names) {
                $input = Get-ComputerInput $computer

                if ($input) {
                    $computers += $input
                }
            }
        }
    }
}

End {
    $success = $false
    $autopilotArgs = $null

    if (-not $canProcess) {
        break
    } elseif ($Online -and $InputFile) {
        Write-Log "Uploading CSV data directly to Microsoft Intune..."
        $result = Get-HashCSV $computers
        $success = $result['success']
        $outputFile = $result['outputFile']
    } elseif ($Online) {
        Write-Log "Uploading hardware information directly to Microsoft Intune..."
        $effectiveAppSecret = Set-EffectiveAppSecret

        if (-not $scriptPath) {
            $success = Import-AutopilotData $computers
        } elseif ($Interactive) {
            Write-Log "You will be prompted to authenticate to Microsoft Graph" -Level Warning
            $autopilotArgs = @("-File `"$scriptPath`"")
            $autopilotArgs += New-AutopilotArgs
        } elseif ($AppTenantId -and $AppId -and $effectiveAppSecret) {
            Write-Log "Using app registration credentials"
            $autopilotArgs = @("-File `"$scriptPath`"")
            $autopilotArgs += New-AutopilotArgs -BaseParams @{ AppSecret = $effectiveAppSecret }
        } else {
            if (-not $effectiveAppSecret) {
                Write-Log "When using -Online with non-interactive authentication, you must provide either -AppSecret or -KeyVaultName and -SecretName." -Level Error
            }

            if (-not $($AppTenantId -and $AppId)) {
                Write-Log "When using -Online with non-interactive authentication, you must provide -AppTenantId and -AppId." -Level Error
            }
        }

        if ($autopilotArgs) {
            Write-Host $autopilotArgs

            $p = Start-Process "$powershell" -ArgumentList $autopilotArgs `
                -NoNewWindow -Wait -PassThru `
                -RedirectStandardOutput $OutputLogFilePath `
                -RedirectStandardError $ErrorLogFilePath `
                -ErrorAction Stop

            # $p.ExitCode is 0 even if the script errors, so we have to be sure it succeeded
            $output = Get-Content $OutputLogFilePath -Raw -ErrorAction SilentlyContinue
            $errors = Get-Content $ErrorLogFilePath -Raw -ErrorAction SilentlyContinue
            $hasSuccess = $output -match "devices imported successfully" -or $output -match "All devices synced"
            $hasErrors = $errors -or
                         $output -match "0 devices imported successfully" -or
                         $output -match "Authentication needed" -or
                         $output -match "invalid_client" -or
                         $output -match "Invalid choice"

            $success = $p -and $($p.ExitCode -eq 0) -and $hasSuccess -and $(-not $hasErrors)
            Remove-Item $OutputLogFilePath, $ErrorLogFilePath -ErrorAction SilentlyContinue
        }
    } else {
        Write-Log "Exporting hardware information to CSV..."
        $result = Get-HashCSV $computers
        $success = $result['success']
        $outputFile = $result['outputFile']
    }

    $hasFile = if ($outputFile) { $(Test-Path -Path $outputFile) } else { $false }
    $fileSize = if ($hasFile) { $(Get-Item $outputFile).Length } else { 0 }
    if ($output) { Write-Log $output }

    if ($success -and $Online) {
        Write-Log "Hardware information uploaded successfully" -Level Success
    } elseif ($success) {
        Write-Log "Hardware information saved successfully ($fileSize bytes)!" -Level Success
        Write-Log "File location: $outputFile"
    } elseif ($errors) {
        Write-Log $errors -Level Error
    } else {
        if ($Online) {
            Write-Log "Failed uploading hardware information" -Level Error
        } else {
            Write-Log "Failed writing hardware information to $outputFile" -Level Error
        }

        $result = @{ Online = $Online; success = $success; hasFile = $hasFile; fileSize = $fileSize }
        if ($p) { $result['ExitCode'] = $p.ExitCode }
        Write-Log $(($result.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join "; ")
    }

    if ($success) {
        $exitCode = 0
    } else {
        Write-Log "Operation failed" -Level Error
    }

    Write-Log "Log file available at: $LogFilePath"
    exit $exitCode
}
