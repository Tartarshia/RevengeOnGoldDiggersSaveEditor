[CmdletBinding()]
param(
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvRoot = Join-Path $projectRoot ".venv"
$python = Join-Path $venvRoot "Scripts\python.exe"
$artifactRoot = Join-Path $projectRoot "artifacts"
$archiveName = "RevengeOnGoldDiggersSaveEditor-v$Version-windows-x64.zip"
$archivePath = Join-Path $artifactRoot $archiveName

if (-not (Test-Path -LiteralPath $python)) {
    py -3 -m venv $venvRoot
}

& $python -m pip install --disable-pip-version-check -r (Join-Path $projectRoot "requirements-build.txt")
& $python -m unittest -v test_public.py
& $python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name "RevengeOnGoldDiggersSaveEditor" `
    --add-data "$(Join-Path $projectRoot 'references\story_graphs.json');references" `
    --add-data "$(Join-Path $projectRoot 'steam_helper.js');." `
    (Join-Path $projectRoot "editor.py")

New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
if (Test-Path -LiteralPath $archivePath) {
    Remove-Item -LiteralPath $archivePath -Force
}
Compress-Archive -LiteralPath @(
    (Join-Path $projectRoot "dist\RevengeOnGoldDiggersSaveEditor.exe"),
    (Join-Path $projectRoot "README.md"),
    (Join-Path $projectRoot "LICENSE")
) -DestinationPath $archivePath -CompressionLevel Optimal

Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath
