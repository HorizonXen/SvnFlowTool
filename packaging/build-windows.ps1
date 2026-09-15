[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
python (Join-Path $Root "packaging\build_windows.py")
if ($LASTEXITCODE -ne 0) { throw "Windows package build failed." }

$Release = Get-Content -LiteralPath (Join-Path $Root "release.json") -Raw | ConvertFrom-Json
$Archive = Join-Path $Root "dist\SvnFlow-Windows-x64-$($Release.version)-$($Release.build).zip"
if (-not (Test-Path -LiteralPath $Archive -PathType Leaf)) { throw "Windows package is missing: $Archive" }
$Hash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$Archive.sha256" -Value "$Hash  $([IO.Path]::GetFileName($Archive))" -Encoding ascii
Write-Host "Windows package built: $Archive"
