[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$TableIndex = "data/reference/kosis_table_summary.csv",
    [string]$OutputDir = "outputs\runs\locked_v1_lexical_topk"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $env:KOSIS_API_KEY) {
    throw "KOSIS_API_KEY is required"
}
if (-not (Test-Path -LiteralPath $TableIndex)) {
    throw "KOSIS table index not found: $TableIndex"
}

& $Python run_kosis_topk_experiment.py `
    --input outputs/gold/gold_measurement_scopefix_kosis_ready.csv `
    --gold outputs/gold/gold_measurement_v1_locked.csv `
    --table-index $TableIndex `
    --retrieval-mode lexical `
    --out-dir $OutputDir `
    --ks 1 2 3 5 `
    --delay 0.05
if ($LASTEXITCODE -ne 0) {
    throw "Top-K experiment failed with exit code $LASTEXITCODE"
}

& $Python score_gold.py `
    --gold-measurement outputs/gold/gold_measurement_v1_locked.csv `
    --candidates "$OutputDir/base_top5/gold_measurement_scopefix_kosis_ready_kosis_candidates_with_meta.csv" `
    --verified "$OutputDir/top2/gold_measurement_scopefix_kosis_ready_top2_verified.csv" `
    --retrieval-k 1 2 3 5 `
    --retrieval-metrics-out "$OutputDir/locked_v1_score_retrieval.csv" `
    --retrieval-slices-dir "$OutputDir/score_slices"
if ($LASTEXITCODE -ne 0) {
    throw "Gold scoring failed with exit code $LASTEXITCODE"
}

Write-Host "locked v1 evaluation complete: $OutputDir"
