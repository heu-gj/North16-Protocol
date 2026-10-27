param(
    [string]$Camera = 'back_04',
    [string]$Project = 'E:\Dataset\north16\datasets\annotations\archive\xanylabeling_20260902_044232',
    [string]$Executable = 'E:\Code\X-AnyLabeling-v4.0.0-beta.3-CPU.exe'
)
$ErrorActionPreference = 'Stop'
if ($Camera -notmatch '^(front|back)_0[1-8]$') { throw 'Invalid camera name' }
$folder = if (Test-Path -LiteralPath (Join-Path $Project 'images') -PathType Container) { Join-Path $Project 'images' } else { Join-Path $Project ('visible\' + $Camera) }
if (!(Test-Path -LiteralPath $folder -PathType Container)) { throw "Folder missing: $folder" }
if (!(Test-Path -LiteralPath $Executable -PathType Leaf)) { throw "Executable missing: $Executable" }
$arguments = @('--filename', $folder, '--output', $folder)
$config = Join-Path $Project 'config.yaml'
if (Test-Path -LiteralPath $config -PathType Leaf) { $arguments += @('--config', $config) }
Start-Process -FilePath $Executable -ArgumentList ($arguments | ForEach-Object { '"' + $_ + '"' }) -WindowStyle Hidden
