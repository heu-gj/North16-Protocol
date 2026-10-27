param(
    [string]$Root = 'E:\20261014',
    [string]$Output = '',
    [string]$Project = '',
    [string]$VisibleModel = 'E:\Code\yolo\weights\yolo11s.pt',
    [string]$InfraredModel = 'E:\Code\yolo\weights\yolo11s.pt'
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Install the North16 GUI environment first.' }
if (!$Output) { $Output = Join-Path (Split-Path -Parent $PSScriptRoot) 'calibration' }
$arguments = @('-m', 'north16', 'register', '--root', $Root, '--output', $Output)
if ($Project) { $arguments += @('--project', $Project) }
if (Test-Path -LiteralPath $VisibleModel -PathType Leaf) { $arguments += @('--visible-model', $VisibleModel) }
if (Test-Path -LiteralPath $InfraredModel -PathType Leaf) { $arguments += @('--infrared-model', $InfraredModel) }
Start-Process -FilePath $python -ArgumentList ($arguments | ForEach-Object { '"' + $_ + '"' }) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
