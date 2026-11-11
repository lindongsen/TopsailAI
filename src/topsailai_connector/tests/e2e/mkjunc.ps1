# Author: DawsonLin
# Purpose: Plant a junction at depth 20 inside the Windows scope, pointing at the
# Node's config directory which sits outside the scope.
#
# The fence must refuse to follow it. A junction is a directory symlink, so the
# same os.Root rule applies, but the escape happens 20 levels below the root where
# a depth-limited or prefix-based check never looks. That is why the junction is
# planted deep rather than at the root: a shallow check would pass this test.

param(
    [string]$Root = 'C:\connector\scope',
    [string]$Target = 'C:\connector\config',
    [int]$Depth = 20
)

$ErrorActionPreference = 'Stop'

$p = $Root
for ($i = 1; $i -le $Depth; $i++) { $p = Join-Path $p 'd' }
$link = Join-Path $p 'escape'

if (Test-Path $link) { Remove-Item -Recurse -Force $link }
cmd /c mklink /J "$link" "$Target" | Out-Null

$item = Get-Item $link
Write-Output ("LINK=" + $link)
Write-Output ("LINKTYPE=" + $item.LinkType)
Write-Output ("INSIDE_SCOPE=" + $link.StartsWith($Root + '\'))
