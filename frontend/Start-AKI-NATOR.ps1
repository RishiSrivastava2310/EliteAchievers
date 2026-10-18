$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$localNode = Join-Path $PSScriptRoot '.tools\node-v22.16.0-win-x64'
if (Test-Path -LiteralPath (Join-Path $localNode 'node.exe')) {
    $env:PATH = "$localNode;$env:PATH"
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Install Node.js 22.12+ from https://nodejs.org, reopen PowerShell, then run this script again.'
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'node_modules'))) {
    & npm.cmd install
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
& npm.cmd run dev
