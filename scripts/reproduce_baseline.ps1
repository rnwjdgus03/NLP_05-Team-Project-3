[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$IncludeApi
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$outputDir = Join-Path $root "outputs\runs\repro_baseline_v1"
$testTemp = Join-Path $root ".test-tmp-repro-baseline-v1-$PID"

function Invoke-Python {
    param([string[]]$Arguments)
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE"
    }
}

function Assert-SameHash {
    param(
        [string]$ExpectedPath,
        [string]$ActualPath
    )
    $expected = (Get-FileHash -Algorithm SHA256 -LiteralPath $ExpectedPath).Hash
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $ActualPath).Hash
    if ($expected -ne $actual) {
        throw "SHA-256 mismatch: $ActualPath"
    }
    Write-Host "hash ok: $ActualPath"
}

Set-Location $root
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

Invoke-Python @(
    "-m", "pytest", "-q", "-p", "no:cacheprovider",
    "--basetemp", $testTemp
)

Invoke-Python @(
    "lock_gold_measurement.py",
    "--input", "outputs/gold/gold_measurement_scopefix.csv",
    "--ready", "outputs/gold/gold_measurement_scopefix_kosis_ready.csv",
    "--output", "$outputDir/gold_measurement_v1_locked.csv",
    "--audit-output", "$outputDir/gold_measurement_v1_label_audit.csv",
    "--metrics-output", "$outputDir/gold_measurement_v1_metrics.json",
    "--report-output", "$outputDir/gold_measurement_v1_report.md",
    "--manifest-output", "$outputDir/gold_measurement_v1_manifest.json",
    "--label-version", "v1",
    "--gate-version", "trade_scope_v1",
    "--source-commit", "0846657",
    "--expect-rows", "109",
    "--expect-ready", "39"
)

Assert-SameHash `
    "outputs/gold/gold_measurement_v1_locked.csv" `
    "$outputDir/gold_measurement_v1_locked.csv"
Assert-SameHash `
    "outputs/gold/gold_measurement_v1_label_audit.csv" `
    "$outputDir/gold_measurement_v1_label_audit.csv"
Assert-SameHash `
    "outputs/gold/gold_measurement_v1_metrics.json" `
    "$outputDir/gold_measurement_v1_metrics.json"

if ($IncludeApi) {
    if (-not $env:KOSIS_API_KEY) {
        throw "KOSIS_API_KEY is required with -IncludeApi"
    }
    Invoke-Python @(
        "verify_gold_coordinates.py",
        "--gold", "data/gold/gold_measurement_tail_100_final.csv",
        "--output", "$outputDir/gold_coordinate_verified.csv",
        "--delay", "0.05"
    )
}

Write-Host "baseline reproduction complete: $outputDir"
