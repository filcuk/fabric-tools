#Requires -Version 5.1
<#
.SYNOPSIS
  Spike: list / add / remove semantic-model RLS role members via Power BI XMLA (TOM).

.DESCRIPTION
  Reads one JSON request from stdin (includes accessToken — never pass the token on argv).
  Requires the SqlServer module from the PowerShell Gallery (TOM assemblies).
  Prefer calling via: fabric-tools debug xmla-roles …

.NOTES
  Capacity must allow XMLA read/write. Membership only (not DAX filter edits).
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Response([hashtable]$Body, [int]$ExitCode = 0) {
    $json = $Body | ConvertTo-Json -Compress -Depth 8
    [Console]::Out.Write($json)
    exit $ExitCode
}

function Write-Err([string]$Code, [string]$Message, [string]$Detail = $null) {
    $body = @{
        ok      = $false
        changed = $false
        code    = $Code
        message = $Message
    }
    if ($Detail) { $body.detail = $Detail }
    Write-Response -Body $body -ExitCode 2
}

function Get-MemberType([string]$Raw) {
    $name = if ([string]::IsNullOrWhiteSpace($Raw)) { 'Auto' } else { $Raw }
    try {
        return [Microsoft.AnalysisServices.Tabular.RoleMemberType]::$name
    }
    catch {
        throw "Invalid memberType '$name' (expected Auto, User, or Group)."
    }
}

function Role-Snapshot($Role) {
    $members = @()
    foreach ($m in $Role.Members) {
        $members += @{
            memberName       = [string]$m.MemberName
            memberId         = $(if ($null -ne $m.MemberID) { [string]$m.MemberID } else { $null })
            identityProvider = [string]$m.IdentityProvider
            memberType       = [string]$m.MemberType
        }
    }
    return @{
        name        = [string]$Role.Name
        description = $(if ($null -ne $Role.Description) { [string]$Role.Description } else { $null })
        members     = $members
    }
}

try {
    $raw = [Console]::In.ReadToEnd()
    if ([string]::IsNullOrWhiteSpace($raw)) {
        Write-Err 'invalid_request' 'Empty stdin; expected JSON request.'
    }

    $req = $raw | ConvertFrom-Json
    $action = [string]$req.action
    $workspace = [string]$req.workspaceName
    $database = [string]$req.databaseName
    $token = [string]$req.accessToken

    if ([string]::IsNullOrWhiteSpace($action)) {
        Write-Err 'invalid_request' 'Missing action (list | member_add | member_remove).'
    }
    if ([string]::IsNullOrWhiteSpace($workspace)) {
        Write-Err 'invalid_request' 'Missing workspaceName.'
    }
    if ([string]::IsNullOrWhiteSpace($database)) {
        Write-Err 'invalid_request' 'Missing databaseName.'
    }
    if ([string]::IsNullOrWhiteSpace($token)) {
        Write-Err 'invalid_request' 'Missing accessToken.'
    }

    if (-not (Get-Module -ListAvailable -Name SqlServer)) {
        Write-Err 'module_missing' (
            'SqlServer PowerShell module not found. ' +
            'Install with: Install-Module SqlServer -Scope CurrentUser'
        )
    }

    Import-Module SqlServer -ErrorAction Stop

    # URL-encode each path segment of the workspace display name for the XMLA URI.
    $encodedWs = ($workspace -split '/' | ForEach-Object { [uri]::EscapeDataString($_) }) -join '/'
    $dataSource = "powerbi://api.powerbi.com/v1.0/myorg/$encodedWs"
    $connectionString = "Data Source=$dataSource;Initial Catalog=$database"

    $server = New-Object Microsoft.AnalysisServices.Tabular.Server
    try {
        $expiration = [DateTimeOffset]::UtcNow.AddHours(1)
        $server.AccessToken = New-Object Microsoft.AnalysisServices.AccessToken($token, $expiration, $null)
    }
    catch {
        # Older SqlServer builds may lack AccessToken; fall back to password=token.
        $connectionString = (
            "Data Source=$dataSource;Initial Catalog=$database;" +
            "User ID=;Password=$token;Persist Security Info=True;Impersonation Level=Impersonate"
        )
    }

    try {
        $server.Connect($connectionString)
    }
    catch {
        Write-Err 'connect_failed' $_.Exception.Message $_.Exception.ToString()
    }

    try {
        $db = $server.Databases.FindByName($database)
        if ($null -eq $db) {
            Write-Err 'database_not_found' "Semantic model '$database' not found on XMLA endpoint."
        }
        $model = $db.Model
        if ($null -eq $model) {
            Write-Err 'model_unavailable' "No tabular model for '$database'."
        }

        switch ($action) {
            'list' {
                $roles = @()
                foreach ($role in $model.Roles) {
                    $roles += Role-Snapshot $role
                }
                Write-Response @{
                    ok      = $true
                    changed = $false
                    message = "Listed $($roles.Count) role(s)."
                    roles   = $roles
                }
            }
            'member_add' {
                $roleName = [string]$req.roleName
                $memberName = [string]$req.member.memberName
                if ([string]::IsNullOrWhiteSpace($roleName)) {
                    Write-Err 'invalid_request' 'Missing roleName.'
                }
                if ([string]::IsNullOrWhiteSpace($memberName)) {
                    Write-Err 'invalid_request' 'Missing member.memberName.'
                }
                $role = $model.Roles.Find($roleName)
                if ($null -eq $role) {
                    Write-Err 'role_not_found' "Role '$roleName' not found on model '$database'."
                }
                foreach ($existing in $role.Members) {
                    if ([string]::Equals($existing.MemberName, $memberName, [StringComparison]::OrdinalIgnoreCase)) {
                        Write-Response @{
                            ok      = $true
                            changed = $false
                            message = "Member '$memberName' already on role '$roleName'."
                            roles   = @((Role-Snapshot $role))
                        }
                    }
                }
                $identityProvider = [string]$req.member.identityProvider
                if ([string]::IsNullOrWhiteSpace($identityProvider)) { $identityProvider = 'AzureAD' }
                $memberType = Get-MemberType ([string]$req.member.memberType)
                $member = New-Object Microsoft.AnalysisServices.Tabular.ExternalModelRoleMember
                $member.MemberName = $memberName
                $member.IdentityProvider = $identityProvider
                $member.MemberType = $memberType
                $memberId = [string]$req.member.memberId
                if (-not [string]::IsNullOrWhiteSpace($memberId)) {
                    $member.MemberID = $memberId
                }
                [void]$role.Members.Add($member)
                $model.SaveChanges()
                Write-Response @{
                    ok      = $true
                    changed = $true
                    message = "Added '$memberName' to role '$roleName'."
                    roles   = @((Role-Snapshot $role))
                }
            }
            'member_remove' {
                $roleName = [string]$req.roleName
                $memberName = [string]$req.member.memberName
                if ([string]::IsNullOrWhiteSpace($roleName)) {
                    Write-Err 'invalid_request' 'Missing roleName.'
                }
                if ([string]::IsNullOrWhiteSpace($memberName)) {
                    Write-Err 'invalid_request' 'Missing member.memberName.'
                }
                $role = $model.Roles.Find($roleName)
                if ($null -eq $role) {
                    Write-Err 'role_not_found' "Role '$roleName' not found on model '$database'."
                }
                $toRemove = $null
                foreach ($existing in $role.Members) {
                    if ([string]::Equals($existing.MemberName, $memberName, [StringComparison]::OrdinalIgnoreCase)) {
                        $toRemove = $existing
                        break
                    }
                }
                if ($null -eq $toRemove) {
                    Write-Response @{
                        ok      = $true
                        changed = $false
                        message = "Member '$memberName' not on role '$roleName'."
                        roles   = @((Role-Snapshot $role))
                    }
                }
                [void]$role.Members.Remove($toRemove)
                $model.SaveChanges()
                Write-Response @{
                    ok      = $true
                    changed = $true
                    message = "Removed '$memberName' from role '$roleName'."
                    roles   = @((Role-Snapshot $role))
                }
            }
            default {
                Write-Err 'invalid_request' "Unknown action '$action' (list | member_add | member_remove)."
            }
        }
    }
    finally {
        if ($null -ne $server -and $server.Connected) {
            $server.Disconnect()
        }
    }
}
catch {
    Write-Err 'unexpected' $_.Exception.Message $_.Exception.ToString()
}
