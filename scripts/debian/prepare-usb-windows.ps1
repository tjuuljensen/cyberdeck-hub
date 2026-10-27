<#
.SYNOPSIS
Prepare a Debian 13 Cyberdeck installer payload for Rufus on Windows.

.DESCRIPTION
Downloads the current official Debian 13 amd64 netinst ISO when -IsoPath is not
provided, verifies the ISO against Debian's SHA512SUMS, and builds a Rufus
Ctrl+Select overlay ZIP from the current Cyberdeck checkout. Windows mounts the
ISO temporarily to read its BIOS and UEFI boot configurations. The ISO and
checksum file are kept in -DownloadDirectory; generated overlay files and the
media manifest are written to -OutputDirectory. This script never writes a USB
device. Rufus handles device selection and asks before erasing it.

.PARAMETER OutputDirectory
Directory for the generated overlay ZIP and media manifest. The directory may
exist. Existing generated media is replaced only when -Overwrite is supplied
and its builder manifest validates.
Defaults to a time-stamped directory under the current user's Downloads folder.

.PARAMETER DownloadDirectory
Directory used to download and retain Debian's ISO and SHA512SUMS. Defaults to
the current user's temporary directory under cyberdeck-installer-cache. Existing
files with the expected names are reused and checked before use.

.PARAMETER IsoPath
Path to a Debian 13 amd64 netinst ISO that has already been downloaded. When
provided, the script does not download an ISO. The file name must follow the
official debian-13.x.y-amd64-netinst.iso pattern.

.PARAMETER ChecksumsPath
Path to the official SHA512SUMS file matching -IsoPath. If omitted, the script
downloads the current Debian SHA512SUMS file into -DownloadDirectory. For an
older pre-downloaded ISO, provide the checksum file from that ISO's official
release directory.

.PARAMETER NoRufusCheck
Skip the final check for a Rufus executable on PATH or in common and registered
installation locations. The script does not install Rufus.

.PARAMETER Overwrite
Replace generated payload files in -OutputDirectory only when its existing
manifest identifies them as output from this builder. The source ISO and
checksum file are not changed.

.EXAMPLE
PS> .\scripts\debian\prepare-usb-windows.ps1
Download the current Debian image and prepare the Rufus overlay using defaults.

.EXAMPLE
PS> .\scripts\debian\prepare-usb-windows.ps1 -DownloadDirectory 'D:\Temp\Cyberdeck ISO' -OutputDirectory 'D:\Temp\Cyberdeck USB'
Keep downloaded source files and generated Rufus payload in separate chosen directories.

.EXAMPLE
PS> .\scripts\debian\prepare-usb-windows.ps1 -IsoPath 'D:\ISO\debian-13.7.0-amd64-netinst.iso' -ChecksumsPath 'D:\ISO\SHA512SUMS'
Use an ISO and matching official checksum file that were downloaded earlier.

.EXAMPLE
PS> .\scripts\debian\prepare-usb-windows.ps1 -NoRufusCheck
Prepare the media without checking whether Rufus is available on this computer.

.EXAMPLE
PS> .\scripts\debian\prepare-usb-windows.ps1 -IsoPath 'D:\ISO\debian-13.7.0-amd64-netinst.iso' -ChecksumsPath 'D:\ISO\SHA512SUMS' -OutputDirectory 'D:\Temp\Cyberdeck USB' -Overwrite
Rebuild the payload in a directory that already contains media from this builder.

.NOTES
Requires Windows PowerShell 5.1 or later, Python 3, and Windows Storage cmdlets
for mounting and reading the ISO. Run from the Cyberdeck repository root.
Review the generated manifest and select the intended USB device in Rufus.
#>
[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $env:USERPROFILE ("Downloads\cyberdeck-installer-media-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))),
    [string]$DownloadDirectory = (Join-Path $env:TEMP 'cyberdeck-installer-cache'),
    [string]$IsoPath,
    [string]$ChecksumsPath,
    [switch]$NoRufusCheck,
    [switch]$Overwrite
)

$ErrorActionPreference = 'Stop'
$imageBase = 'https://cdimage.debian.org/debian-cd/current/amd64/iso-cd'

function Find-RufusExecutable {
    $onPath = Get-Command -Name 'rufus*.exe' -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($onPath) { return $onPath.Source }

    $candidateFiles = @()
    if ($env:ProgramFiles) { $candidateFiles += (Join-Path $env:ProgramFiles 'Rufus\Rufus.exe') }
    if (${env:ProgramFiles(x86)}) { $candidateFiles += (Join-Path ${env:ProgramFiles(x86)} 'Rufus\Rufus.exe') }
    if ($env:LOCALAPPDATA) {
        $candidateFiles += (Join-Path $env:LOCALAPPDATA 'Programs\Rufus\Rufus.exe')
        $candidateFiles += (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\Rufus.exe')
    }
    foreach ($candidate in $candidateFiles) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    $installDirectories = @()
    $uninstallGlobs = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    foreach ($glob in $uninstallGlobs) {
        $entries = Get-ItemProperty -Path $glob -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -match '(?i)^Rufus(?:\s|$)' }
        foreach ($entry in $entries) {
            if ($entry.InstallLocation) { $installDirectories += [string]$entry.InstallLocation }
            if ($entry.DisplayIcon) {
                $iconPath = [string]$entry.DisplayIcon
                if ($iconPath -match '^"([^"]+\.exe)"') {
                    $candidateFiles += $Matches[1]
                } else {
                    $iconPath = $iconPath -replace ',\d+$', ''
                    if ($iconPath -match '(?i)\.exe$') { $candidateFiles += $iconPath }
                }
            }
        }
    }
    foreach ($directory in $installDirectories) {
        if (Test-Path -LiteralPath $directory -PathType Container) {
            $candidateFiles += Get-ChildItem -LiteralPath $directory -Filter 'rufus*.exe' -File `
                -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }
        }
    }

$wingetPackageRoot = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages' }
if ($wingetPackageRoot -and (Test-Path -LiteralPath $wingetPackageRoot -PathType Container)) {
        $candidateFiles += Get-ChildItem -LiteralPath $wingetPackageRoot -Directory -Filter 'Rufus.Rufus*' `
            -ErrorAction SilentlyContinue | ForEach-Object {
                Get-ChildItem -LiteralPath $_.FullName -Filter 'rufus*.exe' -File -Recurse `
                    -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }
            }
    }

    foreach ($candidate in $candidateFiles) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return $null
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $DownloadDirectory -Force | Out-Null
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
$DownloadDirectory = (Resolve-Path -LiteralPath $DownloadDirectory).Path

if (-not $ChecksumsPath) {
    $ChecksumsPath = Join-Path $DownloadDirectory 'SHA512SUMS'
    try {
        Invoke-WebRequest -Uri "$imageBase/SHA512SUMS" -OutFile $ChecksumsPath -UseBasicParsing
    } catch {
        throw "Could not download Debian's official SHA512SUMS file: $($_.Exception.Message)"
    }
} else {
    if (-not (Test-Path -LiteralPath $ChecksumsPath -PathType Leaf)) {
        throw "Checksum file not found: $ChecksumsPath"
    }
    $ChecksumsPath = (Resolve-Path -LiteralPath $ChecksumsPath).Path
}

$checksumText = Get-Content -LiteralPath $ChecksumsPath -Raw
if ($IsoPath) {
    if (-not (Test-Path -LiteralPath $IsoPath -PathType Leaf)) {
        throw "Pre-downloaded ISO not found: $IsoPath"
    }
    $IsoPath = (Resolve-Path -LiteralPath $IsoPath).Path
    $isoName = [System.IO.Path]::GetFileName($IsoPath)
    if ($isoName -notmatch '^debian-13\.\d+\.\d+-amd64-netinst\.iso$') {
        throw "Expected a Debian 13 amd64 netinst ISO file name, got: $isoName"
    }
    $isoEntries = [regex]::Matches($checksumText, "(?m)^([0-9a-fA-F]{128})\s+\*?$([regex]::Escape($isoName))\s*$")
} else {
    $isoEntries = [regex]::Matches($checksumText, '(?m)^([0-9a-fA-F]{128})\s+\*?(debian-13\.\d+\.\d+-amd64-netinst\.iso)\s*$')
    if ($isoEntries.Count -eq 1) {
        $isoName = $isoEntries[0].Groups[2].Value
        $IsoPath = Join-Path $DownloadDirectory $isoName
    }
}
if ($isoEntries.Count -ne 1) {
    throw "Expected exactly one SHA-512 entry for the selected Debian 13 amd64 netinst ISO in $ChecksumsPath. For an older ISO, provide its matching official SHA512SUMS with -ChecksumsPath."
}
$expectedHash = $isoEntries[0].Groups[1].Value.ToLowerInvariant()

if (-not (Test-Path -LiteralPath $IsoPath -PathType Leaf)) {
    if ($PSBoundParameters.ContainsKey('IsoPath')) {
        throw "Pre-downloaded ISO not found: $IsoPath"
    }
    Write-Host "Downloading $isoName from Debian (netinst images are several hundred MB)."
    try {
        Invoke-WebRequest -Uri "$imageBase/$isoName" -OutFile $IsoPath -UseBasicParsing
    } catch {
        throw "Could not download Debian's official ISO: $($_.Exception.Message)"
    }
}
$actualHash = (Get-FileHash -LiteralPath $IsoPath -Algorithm SHA512).Hash.ToLowerInvariant()
if ($actualHash -ne $expectedHash) {
    throw "Debian ISO SHA-512 mismatch. Expected $expectedHash; got $actualHash. Remove the incomplete ISO or select its matching checksum file, then rerun."
}
Write-Host "Verified Debian ISO SHA-512: $actualHash"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Get-Command py -ErrorAction SilentlyContinue
if ($python) {
    $pythonCommand = $python.Source
    $pythonPrefix = @('-3')
} else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { throw 'Python 3 is required to build the source-only Cyberdeck install kit.' }
    $pythonCommand = $python.Source
    $pythonPrefix = @()
}

$temporaryDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("cyberdeck-iso-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporaryDirectory | Out-Null
$diskImage = $null
try {
    $diskImage = Mount-DiskImage -ImagePath $IsoPath -PassThru
    $volumes = @(Get-Volume -DiskImage $diskImage | Where-Object { $_.DriveLetter })
    if ($volumes.Count -eq 0) { throw 'Windows mounted the ISO without an accessible drive letter.' }

    $isoRoot = $null
    $examinedRoots = @()
    foreach ($volume in $volumes) {
        $candidateRoot = "$($volume.DriveLetter):\"
        $examinedRoots += $candidateRoot
        $candidateGrub = Join-Path $candidateRoot 'boot\grub\grub.cfg'
        $candidateIsolinux = Join-Path $candidateRoot 'isolinux\txt.cfg'
        if ((Test-Path -LiteralPath $candidateGrub -PathType Leaf) -and
            (Test-Path -LiteralPath $candidateIsolinux -PathType Leaf)) {
            $isoRoot = $candidateRoot
            $grubSource = $candidateGrub
            $isolinuxSource = $candidateIsolinux
            break
        }
    }
    if (-not $isoRoot) {
        $roots = $examinedRoots -join ', '
        throw "Could not find both Debian installer boot configs on mounted ISO volume(s): $roots."
    }
    $grubCopy = Join-Path $temporaryDirectory 'grub.cfg'
    $isolinuxCopy = Join-Path $temporaryDirectory 'txt.cfg'
    Copy-Item -LiteralPath $grubSource -Destination $grubCopy
    Copy-Item -LiteralPath $isolinuxSource -Destination $isolinuxCopy
} finally {
    if ($diskImage) { Dismount-DiskImage -ImagePath $IsoPath -ErrorAction SilentlyContinue | Out-Null }
}

$builder = Join-Path $repoRoot 'scripts\debian\build_usb_media.py'
try {
    $builderArguments = @()
    $builderArguments += $pythonPrefix
    $builderArguments += $builder
    $builderArguments += @('--repo-root', $repoRoot, '--iso', $IsoPath,
        '--grub-config', $grubCopy, '--isolinux-config', $isolinuxCopy,
        '--output-dir', $OutputDirectory)
    if ($Overwrite) { $builderArguments += '--overwrite' }
    & $pythonCommand @builderArguments
    if ($LASTEXITCODE -ne 0) { throw 'Cyberdeck media payload preparation failed.' }
} finally {
    Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host 'Media payload is ready:'
Write-Host "  Debian ISO:   $IsoPath"
Write-Host "  Rufus overlay: $(Join-Path $OutputDirectory 'cyberdeck-preseed-overlay.zip')"
Write-Host "  Manifest:      $(Join-Path $OutputDirectory 'cyberdeck-media-manifest.json')"
Write-Host '  Preseed boot option: file=/cdrom/preseed.cfg'
Write-Host ''
if (-not $NoRufusCheck) {
    $rufusExecutable = Find-RufusExecutable
    if ($rufusExecutable) {
        Write-Host "Rufus found: $rufusExecutable"
    } else {
        Write-Warning 'Rufus was not found on PATH or in the usual installation locations.'
        Write-Host 'Install it with Windows Package Manager:'
        Write-Host '  winget install --exact --id Rufus.Rufus'
    }
} else {
    Write-Host 'Rufus availability check skipped (-NoRufusCheck).'
}
Write-Host ''
Write-Host 'In Rufus: select the Debian ISO, use ISO Image mode if asked, then hold Ctrl while clicking SELECT and choose cyberdeck-preseed-overlay.zip.'
Write-Host 'Select the intended USB device in Rufus and confirm its erase prompt. Rufus writes the USB; this script does not.'
