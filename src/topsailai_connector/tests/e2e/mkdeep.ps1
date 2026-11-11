# Author: DawsonLin
# Purpose: Build a deeply nested tree under the Windows scope root and report the
# deepest level the filesystem accepts.
#
# Each level holds a file whose content names that level, so a read can be checked
# against the depth it claims. Without that, a fence that silently truncated the
# path would still return success and the test would pass on the wrong file.
#
# The ceiling is the filesystem's, not the Node's: the grammar allows 4096 bytes
# and Windows refuses at MAX_PATH (260 characters), so the tree stops long before
# the grammar limit is reached.

param(
    [string]$Root = 'C:\connector\scope',
    [int]$Max = 300
)

$ErrorActionPreference = 'Stop'

$built = 0
$failAt = 0
$failMsg = ''
$p = $Root

for ($i = 1; $i -le $Max; $i++) {
    $next = Join-Path $p 'd'
    try {
        New-Item -ItemType Directory -Path $next -Force | Out-Null
        Set-Content -Path (Join-Path $next 'f.txt') -Value ("payload-at-" + $i) -NoNewline
        $p = $next
        $built = $i
    } catch {
        $failAt = $i
        $failMsg = $_.Exception.Message
        break
    }
}

Write-Output ("BUILT_DEPTH=" + $built)
Write-Output ("FAILED_AT=" + $failAt)
Write-Output ("FAIL_MSG=" + $failMsg)
Write-Output ("DEEPEST_PATH_LEN=" + $p.Length)
