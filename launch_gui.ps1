param([string]$Folder = '', [string]$Python = '', [string]$Dataset = '')
$ErrorActionPreference = 'Stop'
if (!$Python) {
    $Python = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
}
if (!(Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'GUI environment missing. Install the [gui] extra, then run: north16 gui'
}
if ($Folder -and $Dataset) { throw 'Choose either Dataset or Folder.' }
if (!$Folder -and !$Dataset) {
    $example = Join-Path (Split-Path -Parent $PSScriptRoot) 'datasets'
    if (Test-Path -LiteralPath (Join-Path $example 'samples.txt') -PathType Leaf) { $Dataset = $example }
}
$arguments = @(('"' + (Join-Path $PSScriptRoot 'run_gui.py') + '"'))
if ($Folder) { $arguments += @('--folder', ('"' + $Folder + '"')) }
if ($Dataset) { $arguments += @('--dataset', ('"' + $Dataset + '"')) }
Start-Process -FilePath $Python -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
