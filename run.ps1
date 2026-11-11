$ErrorActionPreference = 'Stop'
$localPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if ($env:VNE_PYTHON) {
    $vnePython = $env:VNE_PYTHON
} elseif (Test-Path -LiteralPath $localPython) {
    $vnePython = $localPython
} else {
    $vnePython = (Get-Command python -ErrorAction Stop).Source
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $vnePython -B (Join-Path $PSScriptRoot 'vne_simulation.py') @args
    $vneExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $vneExitCode
