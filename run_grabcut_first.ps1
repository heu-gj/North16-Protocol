param([int]$Workers = 4)
$ErrorActionPreference = 'Stop'
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
& 'D:\IDE\miniconda3\python.exe' -m north16.annotations.grabcut `
  --root 'E:\Dataset\north16\datasets' `
  --sequence '20260902_044232' `
  --profile 'E:\Dataset\north16\datasets\annotations\grabcut_camera04\parameters.json' `
  --reference 'E:\Dataset\north16\datasets\annotations\demo_camera04\back04' `
  --output 'E:\Dataset\north16\datasets\annotations\grabcut_20260902_044232' `
  --workers $Workers --resume
exit $LASTEXITCODE
