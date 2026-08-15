[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ArchivePath,

    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ExpectedSha256 = '5bbad60dc92647f62a2c4d3cb43e6a6e73c83efab7cfa52d52f3e1def049f4f0'
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Archive = (Resolve-Path -LiteralPath $ArchivePath).Path

$ActualSha256 = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ActualSha256 -ne $ExpectedSha256) {
    throw "SHA-256 mismatch: expected $ExpectedSha256, got $ActualSha256"
}

$RequiredTargets = @(
    'data\indexes\kosis_bge_m3\embeddings.npy',
    'data\indexes\kosis_metadata.sqlite',
    'outputs\locked300_v14_mcp_blind30_predictions\selected.csv',
    'outputs\locked300_v15_retrieval_development\hydration_manifest.json',
    'outputs\locked300_v15_sqlite_coordinates_development\joint_metric_obj_v15_1\mcp_evaluation_period_v15.json'
)

$ExistingTargets = @(
    $RequiredTargets | Where-Object { Test-Path -LiteralPath (Join-Path $RepoRoot $_) }
)
if ($ExistingTargets.Count -gt 0 -and -not $Force) {
    $Rendered = $ExistingTargets -join ', '
    throw "Existing checkpoint files found ($Rendered). Re-run with -Force only if replacement is intended."
}

if ($Force) {
    Expand-Archive -LiteralPath $Archive -DestinationPath $RepoRoot -Force
}
else {
    Expand-Archive -LiteralPath $Archive -DestinationPath $RepoRoot
}

$MissingTargets = @(
    $RequiredTargets | Where-Object { -not (Test-Path -LiteralPath (Join-Path $RepoRoot $_)) }
)
if ($MissingTargets.Count -gt 0) {
    throw "Archive extraction completed but required files are missing: $($MissingTargets -join ', ')"
}

Write-Host "v15 portable assets restored to: $RepoRoot"
Write-Host "SHA-256 verified: $ActualSha256"
