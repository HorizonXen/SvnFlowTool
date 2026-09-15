[CmdletBinding()]
param(
    [string]$InstallDir = $(if ($env:SVNFLOW_INSTALL_DIR) { $env:SVNFLOW_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA "Programs\SvnFlow" }),
    [string]$PackageDir = $(if ($env:SVNFLOW_PACKAGE_DIR) { $env:SVNFLOW_PACKAGE_DIR } else { Join-Path $PSScriptRoot "packages" }),
    [switch]$NoShortcut
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not [Environment]::Is64BitOperatingSystem) {
    throw "This release requires 64-bit Windows 10 or Windows 11."
}

$Release = Get-Content -LiteralPath (Join-Path $PSScriptRoot "release.json") -Raw | ConvertFrom-Json
$ArchiveName = "SvnFlow-Windows-x64-$($Release.version)-$($Release.build).zip"
$Archive = Join-Path $PackageDir $ArchiveName
$ChecksumFile = "$Archive.sha256"

if (-not (Test-Path -LiteralPath $Archive -PathType Leaf)) {
    throw "Windows GUI package is not present: $Archive. This release must not install the validation engine as the desktop application."
}
if (-not (Test-Path -LiteralPath $ChecksumFile -PathType Leaf)) {
    throw "Package checksum is missing: $ChecksumFile"
}

$Expected = ((Get-Content -LiteralPath $ChecksumFile -TotalCount 1) -split '\s+')[0].ToLowerInvariant()
$Actual = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Expected -ne $Actual) {
    throw "Package checksum verification failed."
}

$Staging = Join-Path ([IO.Path]::GetTempPath()) ("svnflow-install-" + [Guid]::NewGuid().ToString("N"))
$Backup = "$InstallDir.previous-$PID"
try {
    New-Item -ItemType Directory -Path $Staging | Out-Null
    Expand-Archive -LiteralPath $Archive -DestinationPath $Staging
    $Executable = Join-Path $Staging "SvnFlow.exe"
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "The archive does not contain SvnFlow.exe."
    }
    $VersionOutput = & $Executable --version
    if ($LASTEXITCODE -ne 0 -or $VersionOutput -notmatch [Regex]::Escape([string]$Release.version)) {
        throw "Package version does not match release.json."
    }

    if (Test-Path -LiteralPath $Backup) {
        throw "Backup path already exists: $Backup"
    }
    $InstallParent = Split-Path -Parent $InstallDir
    if ($InstallParent) {
        New-Item -ItemType Directory -Path $InstallParent -Force | Out-Null
    }
    if (Test-Path -LiteralPath $InstallDir) {
        Move-Item -LiteralPath $InstallDir -Destination $Backup
    }
    try {
        Move-Item -LiteralPath $Staging -Destination $InstallDir
    } catch {
        if (Test-Path -LiteralPath $Backup) {
            Move-Item -LiteralPath $Backup -Destination $InstallDir
        }
        throw
    }
    if (Test-Path -LiteralPath $Backup) {
        Remove-Item -LiteralPath $Backup -Recurse -Force
    }

    if (-not $NoShortcut) {
        $StartMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
        $ShortcutPath = Join-Path $StartMenu "SvnFlow.lnk"
        $Shell = New-Object -ComObject WScript.Shell
        $Shortcut = $Shell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = Join-Path $InstallDir "SvnFlow.exe"
        $Shortcut.WorkingDirectory = $InstallDir
        $Shortcut.Save()
    }

    Write-Host "Installed SvnFlow $($Release.version) ($($Release.build))"
    Write-Host (Join-Path $InstallDir "SvnFlow.exe")
} finally {
    if (Test-Path -LiteralPath $Staging) {
        Remove-Item -LiteralPath $Staging -Recurse -Force
    }
}
