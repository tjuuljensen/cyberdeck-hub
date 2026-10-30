<#
.SYNOPSIS
Builds and deploys Cyberdeck Hub to a generic Debian host from Windows.

.DESCRIPTION
Preview is the default and does not contact the target. -Apply builds the
allowlisted Debian source kit, verifies the SSH target hostname and Debian
identity, transfers and unpacks the kit, previews the Hub installer, applies
the Hub upgrade, and installs CyberChef only when -EnableCyberChef is supplied.
CyberChef uses the Hub hostname and certificate on isolated HTTPS port 8445; it
does not require a separate DNS record or certificate SAN.
The Debian installer manages Kiwix according to whether ZIM files are present;
this script does not force-start a conditionally disabled Kiwix service.

Persistent library data under the configured CYBERDECK_ROOT is retained. Before
applying, the installer creates a root-only snapshot of managed software and
configuration and prints its rollback ID. The snapshot excludes library data
and does not remove packages installed by apt; keep an independent data backup.

.PARAMETER Target
SSH destination or alias. Defaults to cda@cyberdeck.lan.

.PARAMETER ExpectedHost
Expected short hostname used to guard against targeting another machine.

.PARAMETER EnableCyberChef
Install or update the optional CyberChef module on HTTPS port 8445.

.PARAMETER DataRoot
Optional absolute persistent data root below /srv or /home. Leave empty to
preserve the target's configured root or use the Debian default.

.PARAMETER HubSourceRoot
Path to the complete Cyberdeck Hub checkout to deploy.
Defaults to this checkout. All runtime files come from this source.

.PARAMETER Apply
Explicitly transfer and apply the current Debian kit. Without this switch the
script only prints the planned target and services.

.PARAMETER Authenticate
Prime the target user's sudo authentication cache for its configured window.

.PARAMETER UseCachedSudo
Require a valid target sudo cache for apply; fail without prompting if it is
missing or expired.

.PARAMETER RollbackId
Preview restoration of a previous software snapshot by its 32-character ID.

.PARAMETER ExecuteRollback
Restore the selected snapshot after reviewing the rollback preview.

.EXAMPLE
PS> .\scripts\debian\deploy-windows.ps1
Prints the plan without connecting to the host.

.EXAMPLE
PS> .\scripts\debian\deploy-windows.ps1 -Apply
Builds the kit, verifies cyberdeck, and upgrades Hub while preserving optional modules.

.EXAMPLE
PS> .\scripts\debian\deploy-windows.ps1 -Apply -EnableCyberChef
Upgrades Hub and installs the pinned CyberChef module on the isolated HTTPS port.

.EXAMPLE
PS> .\scripts\debian\deploy-windows.ps1 -Authenticate
Authenticates once to prime the target user's sudo cache.

.EXAMPLE
PS> .\scripts\debian\deploy-windows.ps1 -Apply -UseCachedSudo
Applies using a valid sudo cache without prompting for a password.

.EXAMPLE
PS> .\scripts\debian\deploy-windows.ps1 -RollbackId <DEPLOYMENT_ID> -ExecuteRollback
Restores the selected snapshot after verifying the Debian host identity.
#>
[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9_.@-]+$')]
    [string] $Target = 'cda@cyberdeck.lan',

    [ValidatePattern('^[a-z][a-z0-9-]*$')]
    [string] $ExpectedHost = 'cyberdeck',

    [ValidatePattern('^$|^/(srv|home)/[A-Za-z0-9._-]+$')]
    [string] $DataRoot = '',

    [string] $HubSourceRoot = '',

    [switch] $EnableCyberChef,

    [switch] $Authenticate,

    [switch] $UseCachedSudo,

    [ValidatePattern('^[0-9a-f]{32}$')]
    [string] $RollbackId,

    [switch] $ExecuteRollback,

    [switch] $Apply
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$hubSourceRoot = if ($HubSourceRoot) {
    (Resolve-Path -LiteralPath $HubSourceRoot).Path
} else {
    $repoRoot
}
$builderPath = Join-Path $hubSourceRoot 'scripts/debian/build-kit.py'
$appPath = Join-Path $hubSourceRoot 'app/webapp.py'
if (-not (Test-Path -LiteralPath $appPath -PathType Leaf)) {
    throw "Standalone Hub source is missing app/webapp.py: $hubSourceRoot"
}
$versionMatch = Select-String -LiteralPath $appPath -Pattern "^APP_VERSION = '([^']+)'$" |
    Select-Object -First 1
if (-not $versionMatch) { throw 'Could not read APP_VERSION from the Hub application.' }
$appVersion = $versionMatch.Matches[0].Groups[1].Value

function Assert-Executable([string] $Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required executable '$Name' was not found in PATH. Install Windows OpenSSH and Python 3."
    }
}

Assert-Executable 'git'
$gitRoot = & git -C $hubSourceRoot rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0 -or -not $gitRoot) {
    throw "Standalone Hub source must be a Git checkout: $hubSourceRoot"
}
if ((Resolve-Path -LiteralPath $gitRoot.Trim()).Path -ne $hubSourceRoot) {
    throw "Hub source path is not the root of its Git checkout: $hubSourceRoot"
}
$hubCommit = (& git -C $hubSourceRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $hubCommit) { throw 'Could not read the Hub source commit.' }
$hubSourceChanges = @(& git -C $hubSourceRoot status --porcelain)
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the Hub source working tree.' }
$hubSourceClean = $hubSourceChanges.Count -eq 0

function Quote-BashLiteral([string] $Value) {
    return "'" + $Value.Replace("'", "'\''") + "'"
}

function Invoke-Remote([string] $Command, [switch] $AllocateTty, [switch] $UseCachedSudo) {
    if ($AllocateTty) { & ssh -t $Target $Command }
    else { & ssh $Target $Command }
    if ($LASTEXITCODE -eq 255) {
        throw "SSH connection to '$Target' failed or closed unexpectedly. Check the address and host-key prompt. Windows OpenSSH may not resolve a .local name; retry with -Target cda@<server-IPv4>. Check the target release before retrying if this happened during apply."
    }
    if ($LASTEXITCODE -eq 73 -and $UseCachedSudo) {
        throw 'The target sudo cache is missing or expired. Run -Authenticate, then retry -Apply -UseCachedSudo.'
    }
    if ($LASTEXITCODE -ne 0) { throw "SSH command failed with exit code $LASTEXITCODE. The target identity check or remote command failed." }
}

function Assert-RemoteTarget {
    $preflight = @"
set -euo pipefail
test "`$(hostname -s)" = $(Quote-BashLiteral $ExpectedHost) || { echo 'Remote hostname does not match the expected host.' >&2; exit 2; }
test -f /etc/debian_version || { echo 'Target is not a Debian host.' >&2; exit 2; }
printf 'Target verified: %s / Debian %s\n' "`$(hostname -s)" "`$(cat /etc/debian_version)"
"@
    Invoke-Remote "bash -lc $(Quote-BashLiteral $preflight)"
}

if ($Authenticate -and ($Apply -or $RollbackId)) { throw 'Use -Authenticate or deployment apply/rollback, not both in one invocation.' }
if ($UseCachedSudo -and -not ($Apply -or ($RollbackId -and $ExecuteRollback))) { throw '-UseCachedSudo requires -Apply or an executed rollback.' }
if ($ExecuteRollback -and -not $RollbackId) { throw '-ExecuteRollback requires -RollbackId.' }
if ($RollbackId -and $Apply) { throw 'Use -RollbackId or -Apply, not both in one invocation.' }

Write-Output "Target: $Target (expected host: $ExpectedHost)"
Write-Output "Cyberdeck Hub source checkout: $hubSourceRoot"
Write-Output "Cyberdeck Hub source version: $appVersion"
Write-Output "Cyberdeck Hub source commit: $hubCommit"
Write-Output "Cyberdeck Hub source working tree clean: $hubSourceClean"
Write-Output 'Kit components: application, installer, privileged helpers, systemd units, sudoers policy, and profiles from the same Hub checkout.'
Write-Output 'Backup destination: /var/backups/cyberdeck/deployments/<deployment-id> (created before applying).'
Write-Output 'Validation: reject incompatible firewall components before transfer; verify sudo access inside the running web service mount namespace after apply.'
if ($EnableCyberChef) { Write-Output 'CyberChef: install/update pinned build using the Hub hostname on HTTPS port 8445' }
else { Write-Output 'CyberChef: preserve target configuration; pass -EnableCyberChef to install/update it' }
if ($DataRoot) { Write-Output "Persistent library data: $DataRoot" }
else { Write-Output 'Persistent library data: preserve target configuration or use /srv/cyberdeck' }
Write-Output 'Apply actions: build and transfer the Debian kit; verify the target; install Cyberdeck Hub; optionally install CyberChef on isolated HTTPS port 8445; restart required services.'
Write-Output 'Kiwix is started or left inactive by the Debian installer according to the available ZIM files.'
Write-Output 'SSH password authentication can prompt once per SSH/SCP connection; configure an SSH key in ssh-agent to avoid repeated login prompts. sudo may still request the account password once.'
if ($Authenticate) {
    Assert-Executable 'ssh'
    Assert-RemoteTarget
    Invoke-Remote 'sudo -v' -AllocateTty
    Write-Output "Sudo authentication cache primed for $Target ($ExpectedHost). Use -Apply -UseCachedSudo before it expires."
    return
}
if ($RollbackId) {
    Write-Output "Rollback snapshot: $RollbackId"
    Write-Output "Backup: /var/backups/cyberdeck/deployments/$RollbackId"
    if (-not $ExecuteRollback) {
        Write-Output 'Mode: rollback preview; no remote connection or changes made. Add -ExecuteRollback after reviewing the snapshot ID.'
        return
    }
    Assert-Executable 'ssh'
    Assert-RemoteTarget
    $sudo = if ($UseCachedSudo) { 'sudo -n' } else { 'sudo' }
    $rollback = @"
set -euo pipefail
helper=/usr/local/lib/cyberdeck/deploy-helper.py
if [[ ! -f `$helper ]]; then helper="`$HOME/cyberdeck-kit/scripts/debian/deploy-helper.py"; fi
test -f "`$helper" || { echo 'Deployment helper is unavailable; preserve the snapshot and restore the source kit first.' >&2; exit 2; }
$sudo python3 "`$helper" rollback '$RollbackId' $(Quote-BashLiteral $ExpectedHost)
"@
    Invoke-Remote "bash -lc $(Quote-BashLiteral $rollback)" -AllocateTty -UseCachedSudo:$UseCachedSudo
    return
}
if (-not $Apply) {
    Write-Output 'PREVIEW ONLY — no SSH connection or target changes made. Pass -Apply to continue.'
    return
}

foreach ($name in @('python', 'ssh', 'scp')) { Assert-Executable $name }
if (-not $hubSourceClean) {
    throw 'Refusing live deployment from a modified Hub checkout. Commit the candidate changes first so the deployed version can be traced to this source commit.'
}

$kitPath = Join-Path $env:TEMP "cyberdeck-hub-debian-kit-$([guid]::NewGuid().ToString('N')).tar.gz"
$remoteName = "cyberdeck-kit-$([guid]::NewGuid().ToString('N')).tar.gz"
try {
    & python $builderPath --output $kitPath
    if ($LASTEXITCODE -ne 0) { throw "Debian kit build failed with exit code $LASTEXITCODE." }
    $kitHash = (Get-FileHash -LiteralPath $kitPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Output "Source kit: $kitPath"
    Write-Output "Source kit SHA-256: $kitHash"

    Assert-RemoteTarget

    $remoteSpec = "${Target}:$remoteName"
    & scp $kitPath $remoteSpec
    if ($LASTEXITCODE -eq 255) {
        throw "SCP could not connect to '$Target'. Check the address; retry with -Target cda@<server-IPv4> if Windows OpenSSH cannot resolve its name."
    }
    if ($LASTEXITCODE -ne 0) { throw "SCP upload failed with exit code $LASTEXITCODE." }

    $dataRootArgument = if ($DataRoot) { "--data-root $(Quote-BashLiteral $DataRoot)" } else { '' }
    $enableCyberChefArgument = if ($EnableCyberChef) { '1' } else { '0' }
    $applyBlock = @"
set -euo pipefail
bash scripts/debian/install.sh --apply --hostname $(Quote-BashLiteral $ExpectedHost) $dataRootArgument
# Reconcile an already-enabled module after replacing its helper. Leave a
# disabled module disabled; do not depend on a stale active (exited) status.
if [[ -f /etc/cyberdeck/firewall-enabled && ! -L /etc/cyberdeck/firewall-enabled ]]; then
    systemctl enable cyberdeck-firewall.service
    systemctl restart cyberdeck-firewall.service
fi
if [[ $enableCyberChefArgument == 1 ]]; then
    if [[ -e /opt/cyberdeck/modules/cyberchef ]]; then
        python3 scripts/debian/install-cyberchef.py --apply --replace
    else
        python3 scripts/debian/install-cyberchef.py --apply
    fi
fi
systemctl restart cyberdeck-web.service
systemctl is-active --quiet cyberdeck-web.service
printf 'Hub service: active\n'
python3 scripts/debian/verify-runtime.py --expected-host $(Quote-BashLiteral $ExpectedHost)
curl --fail --silent --show-error --retry 10 --retry-connrefused --retry-delay 1 \
    --cacert /etc/cyberdeck/tls/ca.crt \
    --resolve $(Quote-BashLiteral ($ExpectedHost + '.local:443:127.0.0.1')) \
    $(Quote-BashLiteral ('https://' + $ExpectedHost + '.local/')) --output /dev/null
printf 'Hub HTTPS: verified with the installed CA\n'
if [[ $enableCyberChefArgument == 1 ]]; then
    systemctl is-active --quiet cyberdeck-cyberchef.service
    printf 'CyberChef service: active on port 8445\n'
fi
grep -E '^APP_VERSION = ' /usr/local/lib/cyberdeck/app/webapp.py
data_root=`$(sed -n 's/^CYBERDECK_ROOT=//p' /etc/cyberdeck/environment)
[[ -n `$data_root && `$data_root == /* && `$data_root != *' '* ]] || { echo 'Configured library data root is missing or unsafe.' >&2; exit 3; }
if compgen -G "`$data_root/zim/*.zim" >/dev/null; then
    systemctl is-active --quiet cyberdeck-kiwix.service
    printf 'Kiwix service: active\n'
else
    printf 'Kiwix service: no ZIM files are installed; left inactive by design.\n'
fi
"@
    $sudoCommand = if ($UseCachedSudo) { 'sudo -n' } else { 'sudo' }
    $sudoPreflight = if ($UseCachedSudo) {
        "sudo -n -v || { echo 'Target sudo cache is missing or expired.' >&2; exit 73; }"
    } else { '' }
    $remoteScript = @"
set -euo pipefail
test "`$(hostname -s)" = $(Quote-BashLiteral $ExpectedHost) || { echo 'Remote hostname changed; refusing deployment.' >&2; exit 2; }
test -f /etc/debian_version || { echo 'Target is not a Debian host.' >&2; exit 2; }
stage="`$HOME/cyberdeck-hub-deploy-$([guid]::NewGuid().ToString('N'))"
mkdir -m 0700 -- "`$stage"
printf '%s  %s\n' $(Quote-BashLiteral $kitHash) "`$HOME/$remoteName" | sha256sum --check --status
tar -xzf "`$HOME/$remoteName" -C "`$stage"
rm -- "`$HOME/$remoteName"
cd "`$stage"
printf 'Staged complete Hub kit: %s\n' "`$stage"
printf 'Source commit: %s / SHA-256: %s\n' $(Quote-BashLiteral $hubCommit) $(Quote-BashLiteral $kitHash)
bash scripts/debian/install.sh --hostname $(Quote-BashLiteral $ExpectedHost) $dataRootArgument
if [[ $enableCyberChefArgument == 1 ]]; then
    python3 scripts/debian/install-cyberchef.py
fi
if [[ $enableCyberChefArgument == 1 ]]; then
    if [[ -L /opt/cyberdeck/modules/cyberchef || -L /opt/cyberdeck/modules/cyberchef.previous ]]; then
        echo 'Refusing a symlinked CyberChef module path.' >&2
        exit 3
    fi
fi
$sudoPreflight
$sudoCommand bash -c $(Quote-BashLiteral $applyBlock)
"@
    Invoke-Remote "bash -lc $(Quote-BashLiteral $remoteScript)" -AllocateTty -UseCachedSudo:$UseCachedSudo
}
finally {
    if (Test-Path -LiteralPath $kitPath) { Remove-Item -LiteralPath $kitPath -Force }
}
