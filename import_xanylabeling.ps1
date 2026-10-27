param(
    [string]$Project = 'E:\Dataset\north16\datasets\annotations\archive\xanylabeling_20260902_044232',
    [string]$Output = '',
    [switch]$ChangedOnly,
    [switch]$Preview
)
$ErrorActionPreference = 'Stop'
if (!$Output -and !(Test-Path -LiteralPath (Join-Path $Project 'dataset.json') -PathType Leaf)) {
    $Output = Join-Path (Split-Path -Parent $Project) ('xanylabeling_edited_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
}
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
$arguments = @('-m', 'north16.annotations.xanylabeling', 'import', '--project', $Project)
if ($Output) { $arguments += @('--output', $Output) }
if ($ChangedOnly) { $arguments += '--changed-only' }
if ($Preview) { $arguments += '--preview' }
& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') @arguments
if ($LASTEXITCODE -ne 0) { throw "Import failed: $LASTEXITCODE" }
