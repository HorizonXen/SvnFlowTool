[CmdletBinding()]
param(
    [string]$InstallDir = $env:SVNFLOW_INSTALL_DIR,
    [string]$PackageDir = $env:SVNFLOW_PACKAGE_DIR,
    [string]$Repository = $env:SVNFLOW_GITHUB_REPOSITORY,
    [string]$ReleaseBaseUrl = $env:SVNFLOW_RELEASE_BASE_URL,
    [switch]$ValidatePaths,
    [switch]$NoShortcut
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ScriptRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ScriptRoot)) {
    $ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $LocalPrograms = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
    if ([string]::IsNullOrWhiteSpace($LocalPrograms)) {
        throw "Windows LocalApplicationData directory is unavailable. Pass -InstallDir explicitly."
    }
    $InstallDir = Join-Path $LocalPrograms "Programs\SvnFlow"
}
if ([string]::IsNullOrWhiteSpace($PackageDir)) {
    $PackageDir = Join-Path $ScriptRoot "packages"
}
if ($ValidatePaths) {
    Write-Output "SvnFlow installer paths ready."
    return
}

if (-not [Environment]::Is64BitOperatingSystem) {
    throw "This release requires 64-bit Windows 10 or Windows 11."
}

$DownloadRoot = $null
$ReleasePath = Join-Path $ScriptRoot "release.json"
if (-not (Test-Path -LiteralPath $ReleasePath -PathType Leaf)) {
    $DownloadRoot = Join-Path ([IO.Path]::GetTempPath()) ("svnflow-download-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $DownloadRoot | Out-Null
    $PackageDir = $DownloadRoot
    $ReleasePath = Join-Path $DownloadRoot "release.json"
    if (-not $ReleaseBaseUrl) {
        $TargetRepository = if ($Repository) { $Repository } else { "HorizonXen/SvnFlowTool" }
        $ReleaseBaseUrl = "https://raw.githubusercontent.com/$TargetRepository/main"
    }
    $Headers = @{ "User-Agent" = "SvnFlow-Windows-Installer" }
    Invoke-WebRequest -Headers $Headers -Uri "$ReleaseBaseUrl/release.json" -OutFile $ReleasePath
}

$Release = Get-Content -LiteralPath $ReleasePath -Raw | ConvertFrom-Json
$ArchiveName = "SvnFlow-Windows-x64-$($Release.version)-$($Release.build).zip"
$Archive = Join-Path $PackageDir $ArchiveName
$ChecksumFile = "$Archive.sha256"

if ($DownloadRoot) {
    foreach ($Name in @($ArchiveName, "$ArchiveName.sha256")) {
        Invoke-WebRequest -Headers $Headers -Uri "$ReleaseBaseUrl/packages/$Name" -OutFile (Join-Path $DownloadRoot $Name)
    }
}

if (-not (Test-Path -LiteralPath $Archive -PathType Leaf)) {
    throw "Windows package is not present: $Archive."
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
    if ($DownloadRoot -and (Test-Path -LiteralPath $DownloadRoot)) {
        Remove-Item -LiteralPath $DownloadRoot -Recurse -Force
    }
}
