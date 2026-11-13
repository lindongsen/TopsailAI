# Author: DawsonLin
# Purpose: Start the Node from an unpacked bundle, on Windows.
#
# This is the Windows counterpart of start.sh and it does the same job: turn the
# human-edited scopes.txt into policy.yaml on the machine that will serve the
# files, then start the Node with the documented environment variables.
#
# It is a separate script rather than a branch inside start.sh because the two
# platforms disagree about paths in ways that cannot be papered over: a Windows
# path has a drive letter, a backslash separator and a case-insensitive
# comparison, and a POSIX shell cannot express any of those. A single script with
# platform branches would be a script whose Windows half is never exercised by
# the person editing the POSIX half.
#
# Every refusal below is a refusal the Node would also make, moved earlier so the
# message appears next to the person who can fix it. The config-directory overlap
# check is the exception: the Node does not yet perform it, and the bundle keeps
# its credentials inside its own folder, which is exactly the layout that check
# exists to refuse.

$ErrorActionPreference = 'Stop'

# Resolve-PhysicalPath returns a path with every junction and symbolic link in it
# followed, so two paths that name the same directory compare equal.
#
# Resolve-Path is not enough: on PowerShell 5.1 it returns a junction's own path
# unchanged, so a bundle reached through a junction would compare its unresolved
# path against a scope path that was resolved, and the config-overlap guard below
# would never match. The walk is component by component because a junction can sit
# at any level, not only at the leaf.
function Resolve-PhysicalPath([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($full)
    $current = $root
    $parts = $full.Substring($root.Length).Split([char[]]@('\', '/'), [System.StringSplitOptions]::RemoveEmptyEntries)
    foreach ($part in $parts) {
        $current = Join-Path $current $part
        $item = Get-Item -LiteralPath $current -Force -ErrorAction SilentlyContinue
        if ($null -eq $item) { continue }
        if ($item.LinkType -ne 'Junction' -and $item.LinkType -ne 'SymbolicLink') { continue }
        $target = $item.Target
        if ($target -is [array]) { $target = $target[0] }
        if (-not $target) { continue }
        if (-not [System.IO.Path]::IsPathRooted($target)) {
            $target = Join-Path (Split-Path -Parent $current) $target
        }
        $current = Resolve-PhysicalPath $target
    }
    return $current
}

$Here = Resolve-PhysicalPath (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ConfigDir = Join-Path $Here 'config'
$Policy = Join-Path $ConfigDir 'policy.yaml'
$ScopesFile = Join-Path $Here 'scopes.txt'
$ServerUrlFile = Join-Path $Here 'server_url'
$TokenFile = Join-Path $ConfigDir 'tunnel_token'
$NodeBinary = Join-Path $Here 'connector-node.exe'

function Fail([string]$Message) {
    Write-Error "start: $Message"
    exit 1
}

if (-not (Test-Path -LiteralPath $NodeBinary)) { Fail "$NodeBinary is missing" }
if (-not (Test-Path -LiteralPath $ScopesFile)) { Fail "$ScopesFile is missing; it lists the folders this Node exposes" }
if (-not (Test-Path -LiteralPath $ServerUrlFile)) { Fail "$ServerUrlFile is missing; it holds the Server address" }
if (-not (Test-Path -LiteralPath $ConfigDir)) { New-Item -ItemType Directory -Path $ConfigDir | Out-Null }

$ServerUrl = (Get-Content -LiteralPath $ServerUrlFile -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($ServerUrl)) { Fail "$ServerUrlFile is empty" }

# The tunnel token comes from the bundle when the operator provisioned one, and
# from the environment otherwise. It is never echoed: the only thing printed is
# whether it was found, because a token in a terminal is a token in a scrollback
# buffer.
if (Test-Path -LiteralPath $TokenFile) {
    $TunnelToken = (Get-Content -LiteralPath $TokenFile -Raw).Trim()
} else {
    $TunnelToken = $env:CONNECTOR_NODE_TUNNEL_TOKEN
}
if ([string]::IsNullOrWhiteSpace($TunnelToken)) {
    Fail "no tunnel token: the bundle has no config\tunnel_token and CONNECTOR_NODE_TUNNEL_TOKEN is unset"
}

# Resolve-ScopePath turns one entry into an absolute path.
#
# A relative path is resolved against the bundle directory rather than refused.
# The Node refuses a relative path because it would resolve against whatever
# directory the process inherited; resolving against the bundle directory is
# deterministic, because that directory is fixed by where the user unzipped it.
function Resolve-ScopePath([string]$Value) {
    if ([System.IO.Path]::IsPathRooted($Value)) {
        return $Value
    }
    return (Join-Path $Here $Value)
}

# Test-Within reports whether the first path is the second path or sits inside
# it. The comparison is case-insensitive because Windows paths are, and a
# case-sensitive check would let C:\Bundle\CONFIG slip past a rule written for
# C:\Bundle\config.
function Test-Within([string]$Child, [string]$Parent) {
    $childFull = [System.IO.Path]::GetFullPath($Child).TrimEnd('\', '/')
    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    if ([string]::Equals($childFull, $parentFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    $prefix = $parentFull + [System.IO.Path]::DirectorySeparatorChar
    return $childFull.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
}

# ConvertTo-YamlScalar quotes a path so the policy parses whatever the path
# contains. A plain scalar breaks on ' #', ': ' or a leading special character,
# and a policy that fails to parse is a Node that refuses to start.
function ConvertTo-YamlScalar([string]$Value) {
    $escaped = $Value.Replace('\', '\\').Replace('"', '\"')
    return '"' + $escaped + '"'
}

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add('version: 1')
$lines.Add('scopes:')

$grants = New-Object System.Collections.Generic.List[string]
$count = 0
$seen = @{}

foreach ($raw in (Get-Content -LiteralPath $ScopesFile)) {
    $line = $raw.Trim()
    if ($line -eq '' -or $line.StartsWith('#')) { continue }
    if (-not $line.Contains('=')) { Fail "scopes.txt line '$line' is not name=path" }

    $name = $line.Substring(0, $line.IndexOf('='))
    $path = $line.Substring($line.IndexOf('=') + 1)
    if ([string]::IsNullOrWhiteSpace($path)) { Fail "scope '$name' has an empty path" }

    # The scope name rule is the Node's own whitelist, repeated because
    # scopes.txt is edited after packaging.
    if ($name -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]*$') {
        Fail "scope name '$name' must start with a letter or a digit and contain only letters, digits, '-' and '_'"
    }
    if ($seen.ContainsKey($name)) { Fail "scope '$name' is listed twice" }
    $seen[$name] = $true

    $resolved = Resolve-ScopePath $path
    if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
        Fail "scope '$name' path '$resolved' is not a directory on this machine"
    }
    $resolved = Resolve-PhysicalPath $resolved

    # The Node refuses these at startup. Checking them here names the scope and
    # the reason, which a startup failure from inside the binary does not do as
    # clearly.
    $root = [System.IO.Path]::GetPathRoot($resolved)
    if ([string]::Equals($resolved.TrimEnd('\'), $root.TrimEnd('\'), [System.StringComparison]::OrdinalIgnoreCase)) {
        Fail "scope '$name' is the root of a drive, whose blast radius is the whole volume"
    }
    $homeDir = [Environment]::GetFolderPath('UserProfile')
    if ($homeDir -and [string]::Equals($resolved.TrimEnd('\'), $homeDir.TrimEnd('\'), [System.StringComparison]::OrdinalIgnoreCase)) {
        Fail "scope '$name' is the home directory, whose blast radius is every file you own"
    }

    # The bundle keeps its credentials in .\config. A scope that contains that
    # directory lets a caller list the names and sizes of the identity and policy
    # files, so the overlap is refused rather than denied per request.
    if ((Test-Within $resolved $ConfigDir) -or (Test-Within $ConfigDir $resolved)) {
        Fail "scope '$name' path '$resolved' overlaps the bundle's config directory $ConfigDir; move the folder or the bundle"
    }

    $lines.Add("  ${name}:")
    $lines.Add("    path: " + (ConvertTo-YamlScalar $resolved))
    $grants.Add("  - scope: $name")
    $grants.Add("    permissions: [read, list, stat]")
    $count++
    Write-Host "start: scope $name -> $resolved"
}

if ($count -eq 0) { Fail "scopes.txt defines no scope; a Node that exposes nothing serves nothing" }

$lines.Add('grants:')
foreach ($grant in $grants) { $lines.Add($grant) }

# The policy is written through a temporary file and moved into place, so a
# failure halfway through does not leave a half-written policy that the Node
# would refuse to load on the next start.
$temporary = "$Policy.tmp"
Set-Content -LiteralPath $temporary -Value $lines -Encoding utf8
Move-Item -LiteralPath $temporary -Destination $Policy -Force

Write-Host "start: server $ServerUrl"
Write-Host "start: config $ConfigDir"

# The four variables are the documented Node surface. The token is set here and
# nowhere else, so the Node reads it from the environment exactly as
# docs/Environment_Variables.md describes.
$env:CONNECTOR_NODE_SERVER_URL = $ServerUrl
$env:CONNECTOR_NODE_TUNNEL_TOKEN = $TunnelToken
$env:CONNECTOR_NODE_CONFIG_DIR = $ConfigDir
$env:CONNECTOR_NODE_POLICY_FILE = $Policy

& $NodeBinary run
exit $LASTEXITCODE
