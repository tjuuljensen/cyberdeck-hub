#!/usr/bin/env bash
# Install Cyberdeck Hub on an existing Debian 13 host.
#
# Examples:
#   bash scripts/debian/install.sh
#   bash scripts/debian/install.sh --hostname cyberdeck
#   sudo bash scripts/debian/install.sh --apply [--offline]
#   sudo bash scripts/debian/install.sh --apply --data-root /home/cyberdeck-data
#
# Parameters:
#   --apply            Apply changes to the host: install/configure
#                      packages, accounts, data and TLS files, and services.
#                      Without it, print a preview and make no host changes.
#   --offline          Use already available packages and skip online package
#                      setup and CyberChef installation.
#   --hostname NAME    Expected short host name used for the Hub address and
#                      certificates. Prompted interactively when omitted; it
#                      must match the host's current short hostname.
#   --data-root PATH   Library data directory, a direct child of /srv or /home
#                      (default: /srv/cyberdeck). Avoid changing an existing
#                      populated library location; use the storage migration
#                      procedure instead.
#
# Run from a complete source checkout on the intended Debian 13 host. The
# installer preserves the existing Debian installation; it does not partition
# disks, rename the host, or modify existing interface settings or firewall
# rules. Online setup installs pinned CyberChef files but leaves the service
# disabled. After setup, choose an installed profile or import a configuration
# JSON or bundle in Admin > Import.
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
app_source="$repo_root/app"
service_source="$repo_root/config/debian/systemd"
sleep_source="$service_source/sleep.conf.d/90-cyberdeck.conf"
logind_source="$service_source/logind.conf.d/90-cyberdeck.conf"
empty_manifest="$repo_root/config/debian/library-manifest.json"
starter_profile="$repo_root/config/debian/starter.json"
profiles_source="$repo_root/config/debian/profiles"
starter_asset="$repo_root/assets/hub/library-startup.html"
hostname_expected=''
data_root=''
data_root_explicit=0
apply=0
offline=0

usage() {
    cat <<'EOF'
Cyberdeck Hub Debian 13 installer. Missing names are requested interactively.
Preview is the default; --apply changes the host.

  bash scripts/debian/install.sh
  bash scripts/debian/install.sh --hostname SERVER-NAME
  sudo bash scripts/debian/install.sh --apply [--offline]
  sudo bash scripts/debian/install.sh --apply --data-root /home/cyberdeck-data

The installer keeps the existing Debian installation. It installs
NetworkManager for interface reporting and hotspot support; Debian's package
defaults may start its service. The installer does not rewrite interface files
or connection profiles, partition disks, change the host name, choose hotspot
settings, or modify firewall rules. Run it from a complete Cyberdeck source
checkout on the intended host.
After setup, choose an installed profile or upload a Cyberdeck configuration
JSON or bundle in Admin > Import.
Online setup installs the pinned CyberChef module and leaves it disabled.
Admin can enable it when needed. Offline setup cannot download CyberChef and
does not install it.
EOF
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

while (($#)); do
    case "$1" in
        --apply) apply=1 ;;
        --offline) offline=1 ;;
        --hostname)
            (($# >= 2)) || { usage; die '--hostname requires a value.'; }
            hostname_expected=$2
            shift
            ;;
        --data-root)
            (($# >= 2)) || { usage; die '--data-root requires an absolute path under /srv or /home.'; }
            data_root=$2
            data_root_explicit=1
            shift
            ;;
        -h|--help) usage; exit 0 ;;
        *) usage; die "Unknown option: $1" ;;
    esac
    shift
done

# Preserve an existing storage root without evaluating the environment file as shell code.
configured_roots=()
if [[ -f /etc/cyberdeck/environment && ! -L /etc/cyberdeck/environment ]]; then
    mapfile -t configured_roots < <(sed -n 's/^CYBERDECK_ROOT=//p' /etc/cyberdeck/environment)
    ((${#configured_roots[@]} <= 1)) || die 'The configured CYBERDECK_ROOT is ambiguous; repair /etc/cyberdeck/environment first.'
    if (( ! data_root_explicit )) && ((${#configured_roots[@]} == 1)); then
        data_root=${configured_roots[0]}
    fi
fi

# On a fresh interactive install, offer a separate /home filesystem when it has
# more free space than /. Keep upgrades and explicit --data-root choices stable.
storage_recommendation=''
if (( ! data_root_explicit )) && ((${#configured_roots[@]} == 0)) &&
   [[ -d /home && ! -L /home ]] &&
   [[ $(stat -c '%d' /) != "$(stat -c '%d' /home)" ]]; then
    root_available=$(df -B1 --output=avail / | tail -n 1 | tr -d '[:space:]')
    home_available=$(df -B1 --output=avail /home | tail -n 1 | tr -d '[:space:]')
    if [[ $root_available =~ ^[0-9]+$ && $home_available =~ ^[0-9]+$ ]] &&
       (( home_available > root_available )); then
        storage_recommendation=/home/cyberdeck-data
        # Keep previews and deploy-launcher preflight non-interactive. Confirm
        # the recommendation once during a fresh interactive apply; the chosen
        # path is then persisted in /etc/cyberdeck/environment for upgrades.
        if (( apply )) && [[ -t 0 ]]; then
            printf 'Separate /home filesystem detected: %s free; / has %s free.\n' \
                "$(df -h --output=avail /home | tail -n 1 | xargs)" \
                "$(df -h --output=avail / | tail -n 1 | xargs)" >&2
            read -r -p 'Use /home/cyberdeck-data for library data? [Y/n]: ' storage_choice ||
                die 'Could not read the storage choice. Re-run with --data-root PATH.'
            storage_choice=${storage_choice%$'\r'}
            case "$storage_choice" in
                ''|y|Y|yes|YES|Yes) data_root=$storage_recommendation ;;
                n|N|no|NO|No) ;;
                *) die 'Answer yes or no for the library storage location.' ;;
            esac
        fi
    fi
fi
data_root=${data_root:-/srv/cyberdeck}
[[ $data_root =~ ^/(srv|home)/[A-Za-z0-9._-]+$ && $data_root != /srv && $data_root != /home ]] ||
    die 'Use a direct child path under /srv or /home for --data-root (no spaces, symlinks, or traversal).'
IFS=/ read -r -a data_components <<< "$data_root"
walk_path=''
for component in "${data_components[@]}"; do
    [[ -z $component ]] && continue
    walk_path+="/$component"
    [[ ! -L $walk_path ]] || die "Refusing symlink in data-root path: $walk_path"
done
if (( data_root_explicit )) && ((${#configured_roots[@]} == 1)); then
    configured_root=${configured_roots[0]}
    if [[ -n $configured_root && $configured_root != "$data_root" && -d $configured_root ]] &&
       find "$configured_root" -mindepth 1 -print -quit | grep -q .; then
        die 'The current library contains data. Follow the Debian storage migration procedure before changing --data-root.'
    fi
fi

if [[ -z $hostname_expected ]]; then
    suggested_hostname=$(hostname -s 2>/dev/null || true)
    while [[ -z $hostname_expected ]]; do
        if [[ -n $suggested_hostname ]]; then
            read -r -p "Server name [$suggested_hostname]: " hostname_expected ||
                die 'Could not read the server name. Re-run with --hostname SERVER-NAME.'
            hostname_expected=${hostname_expected%$'\r'}
            hostname_expected=${hostname_expected:-$suggested_hostname}
        else
            read -r -p 'Server name: ' hostname_expected ||
                die 'Could not read the server name. Re-run with --hostname SERVER-NAME.'
            hostname_expected=${hostname_expected%$'\r'}
        fi
    done
fi
[[ $hostname_expected =~ ^([a-z])([a-z0-9-]{0,61}[a-z0-9])?$ ]] ||
    die 'Use a lowercase server name beginning with a letter and containing only letters, digits, and hyphens.'
[[ -f "$app_source/webapp.py" && -f "$app_source/library.py" &&
   -f "$app_source/legacy_card_translations.json" &&
   -d "$app_source/static" && -d "$app_source/templates" &&
   -d "$app_source/translations" && -f "$service_source/cyberdeck-web.service" ]] ||
    die 'The complete Hub source and Debian service files must be present beside this installer.'
[[ -f "$empty_manifest" && -f "$starter_profile" &&
   -f "$sleep_source" && -f "$logind_source" &&
   -f "$service_source/cyberdeck-kiwix.service" &&
   -f "$service_source/cyberdeck-redirect.service" &&
   -f "$service_source/cyberdeck-storage-migration.service" &&
   -f "$service_source/cyberdeck-storage-initialize.service" &&
   -f "$service_source/cyberdeck-storage-existing.service" &&
   -f "$service_source/cyberdeck-storage-recovery.service" &&
   -f "$service_source/cyberdeck-storage-boot-recovery.service" &&
   -f "$service_source/cyberdeck-firewall.service" &&
   -f "$repo_root/config/debian/systemd/cyberdeck-hotspot-autostart.service" &&
   -f "$repo_root/config/debian/systemd/cyberdeck-hotspot-autostart.timer" &&
   -f "$repo_root/config/debian/cyberdeck-hotspot-dns.conf" &&
   -f "$repo_root/config/debian/tmpfiles.d/cyberdeck-storage.conf" &&
   -f "$repo_root/scripts/debian/storage-helper.py" &&
   -f "$repo_root/scripts/debian/wifi-diagnostics.py" &&
   -f "$repo_root/scripts/debian/admin-helper.py" &&
   -f "$repo_root/scripts/debian/host_identity.py" &&
   -f "$repo_root/scripts/debian/http-redirect.py" ]] ||
    die 'The Debian runtime manifest, starter profile, services, and host helpers must be present.'
for source_path in "$repo_root/config" "$repo_root/config/debian" \
                   "$repo_root/config/debian/systemd" \
                   "$repo_root/assets" "$repo_root/assets/hub" \
                   "$service_source" "$app_source/static" \
                   "$service_source/sleep.conf.d" "$service_source/logind.conf.d" \
                   "$app_source/templates" "$app_source/translations"; do
    [[ -d "$source_path" && ! -L "$source_path" ]] ||
        die "Expected a regular, non-symlink source directory: $source_path"
done
if [[ -e "$profiles_source" || -L "$profiles_source" ]]; then
    [[ -d "$profiles_source" && ! -L "$profiles_source" ]] ||
        die "Expected a regular, non-symlink profile directory: $profiles_source"
fi
for source_file in "$app_source/webapp.py" "$app_source/library.py" \
                   "$app_source/legacy_card_translations.json" \
                   "$app_source/kiwix_https.py" \
                   "$service_source/cyberdeck-web.service" \
                   "$service_source/cyberdeck-kiwix.service" \
                   "$service_source/cyberdeck-redirect.service" \
                   "$service_source/cyberdeck-storage-migration.service" \
                   "$service_source/cyberdeck-storage-initialize.service" \
                   "$service_source/cyberdeck-storage-existing.service" \
                   "$service_source/cyberdeck-storage-recovery.service" \
                   "$service_source/cyberdeck-storage-boot-recovery.service" \
                   "$sleep_source" "$logind_source" \
                   "$repo_root/config/debian/systemd/cyberdeck-hotspot-autostart.service" \
                   "$repo_root/config/debian/systemd/cyberdeck-hotspot-autostart.timer" \
                   "$repo_root/config/debian/cyberdeck-hotspot-dns.conf" \
                   "$repo_root/config/debian/tmpfiles.d/cyberdeck-storage.conf" \
                   "$repo_root/scripts/debian/storage-helper.py" \
                   "$repo_root/scripts/debian/wifi-diagnostics.py" \
                   "$repo_root/scripts/debian/deploy-helper.py" \
                   "$repo_root/scripts/debian/admin-helper.py" \
                   "$repo_root/scripts/debian/host_identity.py" \
                   "$repo_root/scripts/debian/http-redirect.py" \
                   "$empty_manifest" "$starter_profile" "$starter_asset"; do
    [[ -f "$source_file" && ! -L "$source_file" ]] ||
        die "Expected a regular, non-symlink source file: $source_file"
done
[[ -s "$starter_asset" ]] || die 'The generic starter profile source file is empty.'
shopt -s nullglob
for source_dir in "$app_source/static" "$app_source/templates" "$app_source/translations"; do
    source_files=("$source_dir"/*)
    ((${#source_files[@]} > 0)) || die "No installable source files in $source_dir."
    for source_file in "${source_files[@]}"; do
        [[ -f "$source_file" && ! -L "$source_file" ]] ||
            die "Expected a regular, non-symlink source file: $source_file"
    done
done
shopt -u nullglob
if [[ -d "$profiles_source" ]]; then
    shopt -s nullglob
    profile_files=("$profiles_source"/*.json)
    for profile_file in "${profile_files[@]}"; do
        [[ -f "$profile_file" && ! -L "$profile_file" &&
           $(basename "$profile_file") =~ ^[a-z0-9][a-z0-9_-]{0,63}\.json$ ]] ||
            die "Expected a regular profile JSON with a safe filename: $profile_file"
    done
    shopt -u nullglob
fi

# Validate the staged helper and policy before packages, backups, or host writes.
python3 "$repo_root/scripts/debian/build-kit.py" --validate-only ||
    die 'The source kit has incompatible runtime components; rebuild a complete Hub kit.'

if (( ! apply )); then
    printf '%s\n' 'PREVIEW ONLY — no changes made.'
    printf 'Library address: https://%s.local/\n' "$hostname_expected"
    printf 'Package mode: %s\n' "$([[ $offline == 1 ]] && printf offline || printf online)"
    printf 'Persistent library data: %s\n' "$data_root"
    data_preview_parent=${data_root%/*}
    if [[ -d $data_preview_parent ]]; then
        printf 'Data filesystem capacity: '
        df -h --output=source,size,avail,target "$data_preview_parent" | tail -n 1 | sed 's/^[[:space:]]*//'
    else
        printf 'Data filesystem capacity: parent directory does not exist yet (%s).\n' "$data_preview_parent"
    fi
    if [[ -n $storage_recommendation && $data_root != "$storage_recommendation" ]]; then
        printf 'Storage suggestion: %s is a separate filesystem with more free space; confirm it during interactive apply or pass --data-root PATH.\n' "$storage_recommendation"
    fi
    printf '%s\n' \
        'Would install/check Debian 13 packages: python3, python3-flask, gunicorn, kiwix-tools, zim-tools, openssl, sudo, avahi-daemon, network-manager, dnsmasq-base, iw, nftables, curl, rsync, parted, e2fsprogs, util-linux.' \
        'Would install the pinned compatible zimcheck validator when Debian supplies an older libzim.' \
        'Would create the unprivileged cyberdeck service user, persistent data directories, a local CA and server certificate.' \
        'Would install Cyberdeck Hub on HTTPS port 443, certificate bootstrap and HTTP redirect on port 80, and Kiwix on loopback port 8080.' \
        'Would enable cyberdeck-web, cyberdeck-kiwix, the hotspot fallback timer, and avahi-daemon; NetworkManager provides nmcli for interface reporting and hotspot management.' \
        'The allowlisted reboot and poweroff controls are available to the Hub administrator.' \
        'Would disable system sleep and logind idle suspend so the headless library stays available.' \
        'Online setup installs the pinned CyberChef module for isolated HTTPS port 8445 and leaves the service disabled; --offline omits it because the archive cannot be downloaded.' \
        'After first boot, create an administrator and import a configuration profile through the admin page.'
    exit 0
fi

[[ $EUID == 0 ]] || die 'Run --apply with sudo on the selected Debian host.'
[[ -r /etc/os-release ]] || die 'Cannot identify the target operating system.'
. /etc/os-release
[[ ${ID:-} == debian && ${VERSION_ID:-} == 13 ]] || die 'Requires Debian 13.'
case "$(dpkg --print-architecture)" in amd64|arm64) ;; *) die 'Supports Debian amd64 and arm64; Pi acceptance remains separate.' ;; esac
[[ -d /run/systemd/system ]] || die 'A running systemd host is required.'
[[ $(hostname -s) == "$hostname_expected" ]] || die 'The requested library name must match the current short hostname.'
for command in dpkg hostname ss systemctl getent id findmnt; do
    command -v "$command" >/dev/null || die "Missing required system command: $command."
done
existing_account=$(getent passwd cyberdeck || true)
if [[ -n $existing_account ]]; then
    IFS=: read -r account_name _ account_uid _ _ account_home account_shell <<< "$existing_account"
    [[ $account_name == cyberdeck && $account_uid =~ ^[0-9]+$ && $account_uid != 0 &&
       $account_home == /nonexistent && $account_shell == /usr/sbin/nologin ]] ||
        die 'The login username cyberdeck is reserved for the Hub service account. Reinstall Debian with another administrator username, such as operator.'
fi
data_parent=${data_root%/*}
[[ -d $data_parent ]] || die "The parent directory for --data-root does not exist: $data_parent"
data_mount=$(findmnt -n -o TARGET -T "$data_parent")
data_mount_options=$(findmnt -n -o OPTIONS -T "$data_parent")
[[ ,$data_mount_options, == *,rw,* ]] || die "The filesystem for $data_root is not mounted read-write."
[[ $data_mount =~ ^/(srv|home)(/[^[:space:]]*)?$ || $data_mount == / ]] ||
    die 'The data-root mount must be /, below /srv, or below /home.'
if [[ $data_root == /home/* && $data_mount != /home && $data_mount != /home/* ]]; then
    die "The /home filesystem is not mounted at $data_root's parent; refusing to store library data on the root filesystem."
fi
[[ -d /home && ! -L /home ]] || die 'Expected /home to be a regular directory for isolated filesystem reporting.'
home_mount=$(findmnt -n -o TARGET -T /home)
home_mount_options=$(findmnt -n -o OPTIONS -T /home)
[[ ,$home_mount_options, == *,rw,* ]] || die 'The /home filesystem must be mounted read-write for separate-volume reporting.'
root_device=$(stat -c '%d' /)
home_device=$(stat -c '%d' /home)
home_probe=/home/.cyberdeck-storage-probe
home_probe_bind=''
home_mount_value=''
if [[ $root_device != "$home_device" ]]; then
    [[ $home_mount == /home || $home_mount == /home/* ]] ||
        die 'The separate /home filesystem has an unexpected mount point.'
    home_mount_value=$home_mount
    home_probe_bind="BindReadOnlyPaths=$home_probe"
    if [[ -e $home_probe || -L $home_probe ]]; then
        [[ -d $home_probe && ! -L $home_probe && $(stat -c '%u:%a' "$home_probe") == 0:555 ]] ||
            die "Refusing an existing path at $home_probe; expected an empty root-owned mode-0555 directory."
        [[ -z $(find "$home_probe" -mindepth 1 -print -quit) ]] ||
            die "Refusing non-empty storage probe directory: $home_probe"
    fi
fi
if (( offline == 0 )); then
    command -v apt-get >/dev/null || die 'Missing apt-get; cannot install the required packages.'
fi
existing_account=$(getent passwd cyberdeck || true)
if [[ -n $existing_account ]]; then
    IFS=: read -r account_name _ account_uid account_gid _ account_home account_shell <<< "$existing_account"
    [[ $account_name == cyberdeck && $account_uid =~ ^[0-9]+$ && $account_uid != 0 &&
       $account_home == /nonexistent && $account_shell == /usr/sbin/nologin &&
       $(id -gn cyberdeck) == cyberdeck ]] ||
        die 'The existing cyberdeck account does not match the unprivileged service-account policy.'
    for account_group in $(id -nG cyberdeck); do
        [[ $account_group == cyberdeck || $account_group == cyberdeck-tls ]] ||
            die "The existing cyberdeck account belongs to unexpected group $account_group."
    done
fi
if ss -ltnH '( sport = :443 )' | grep -q .; then
    systemctl is-active --quiet cyberdeck-web.service || die 'Port 443 is already occupied by another service.'
fi
if ss -ltnH '( sport = :8080 )' | grep -q .; then
    systemctl is-active --quiet cyberdeck-kiwix.service || die 'Port 8080 is already occupied by another service.'
fi
if ss -ltnH '( sport = :80 )' | grep -q .; then
    systemctl is-active --quiet cyberdeck-redirect.service || die 'Port 80 is already occupied by another service.'
fi
for path in /srv /srv/cyberdeck /srv/cyberdeck/zim /srv/cyberdeck/public /srv/cyberdeck/private \
            "$data_root" "$data_root/zim" "$data_root/public" "$data_root/private" \
            /etc/cyberdeck /etc/cyberdeck/tls /etc/systemd/system \
            /etc/systemd/sleep.conf.d /etc/systemd/logind.conf.d /etc/sudoers.d \
            /etc/NetworkManager /etc/NetworkManager/system-connections \
            /etc/NetworkManager/dnsmasq-shared.d \
            /usr/local/lib /usr/local/lib/cyberdeck /usr/local/lib/cyberdeck/app \
            /usr/local/lib/cyberdeck/app/static \
            /usr/local/lib/cyberdeck/app/templates \
            /usr/local/lib/cyberdeck/app/translations \
            /usr/local/lib/cyberdeck/tools \
            /usr/local/lib/cyberdeck/assets /usr/local/lib/cyberdeck/assets/hub \
            /usr/local/lib/cyberdeck/profiles; do
    [[ ! -L $path ]] || die "Refusing symlink: $path"
done
destination_files=(
    /etc/cyberdeck/session.key /etc/cyberdeck/tls/ca.key /etc/cyberdeck/tls/ca.crt
    /etc/cyberdeck/tls/server.key /etc/cyberdeck/tls/server.crt
    /etc/cyberdeck/tls/server.csr /etc/cyberdeck/tls/server.ext /etc/cyberdeck/tls/ca.srl
    /etc/cyberdeck/environment /etc/systemd/system/cyberdeck-web.service
    /etc/systemd/system/cyberdeck-firewall.service /etc/cyberdeck/firewall-enabled
    /etc/systemd/system/cyberdeck-kiwix.service /etc/systemd/system/cyberdeck-redirect.service
    /etc/sudoers.d/cyberdeck-web
    /etc/systemd/system/cyberdeck-hotspot-autostart.service
    /etc/systemd/system/cyberdeck-hotspot-autostart.timer
    /etc/systemd/sleep.conf.d/90-cyberdeck.conf
    /etc/systemd/logind.conf.d/90-cyberdeck.conf
    /etc/NetworkManager/dnsmasq-shared.d/cyberdeck.conf
    /usr/local/lib/cyberdeck/admin-helper.py
    /usr/local/lib/cyberdeck/deploy-helper.py
    /usr/local/lib/cyberdeck/host_identity.py
    /usr/local/lib/cyberdeck/http-redirect.py
    /usr/local/lib/cyberdeck/starter.json /usr/local/lib/cyberdeck/serve-kiwix.sh
    /usr/local/lib/cyberdeck/profiles/starter.json
    /usr/local/lib/cyberdeck/app/webapp.py /usr/local/lib/cyberdeck/app/library.py
    /usr/local/lib/cyberdeck/app/legacy_card_translations.json
    /usr/local/lib/cyberdeck/app/kiwix_https.py
    /usr/local/lib/cyberdeck/app/cyberchef_server.py
    /usr/local/lib/cyberdeck/tools/zimcheck
    /usr/local/lib/cyberdeck/assets/hub/library-startup.html
)
for source_file in "$app_source"/templates/*.html; do
    destination_files+=("/usr/local/lib/cyberdeck/app/templates/$(basename "$source_file")")
done
for source_file in "$app_source"/static/*; do
    destination_files+=("/usr/local/lib/cyberdeck/app/static/$(basename "$source_file")")
done
for source_file in "$app_source"/translations/*.json; do
    destination_files+=("/usr/local/lib/cyberdeck/app/translations/$(basename "$source_file")")
done
destination_files+=(/usr/local/lib/cyberdeck/profiles/*.json)
if [[ -d "$profiles_source" ]]; then
    for source_file in "$profiles_source"/*.json; do
        destination_files+=("/usr/local/lib/cyberdeck/profiles/$(basename "$source_file")")
    done
fi
for file in "${destination_files[@]}"; do
    [[ ! -L $file ]] || die "Refusing symlink: $file"
done
command -v python3 >/dev/null || die 'Python 3 is required to create the deployment recovery snapshot.'
deployment_id=$(python3 "$repo_root/scripts/debian/deploy-helper.py" snapshot "$hostname_expected")
[[ $deployment_id =~ ^[0-9a-f]{32}$ ]] || die 'Could not create a valid deployment recovery ID.'
printf 'Deployment recovery snapshot: %s\nBackup: /var/backups/cyberdeck/deployments/%s\n' \
    "$deployment_id" "$deployment_id"
packages=(python3 python3-flask gunicorn kiwix-tools zim-tools openssl sudo avahi-daemon network-manager dnsmasq-base iw nftables curl rsync parted e2fsprogs util-linux)
if (( offline == 0 )); then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}"
fi
for command in python3 gunicorn kiwix-serve zimcheck openssl visudo systemctl ss avahi-daemon nmcli dnsmasq iw rsync lsblk parted wipefs partprobe mkfs.ext4 blkid findmnt; do
    command -v "$command" >/dev/null || die "Missing $command; install the listed packages or restore the offline package cache."
done
python3 -c 'import flask' || die 'Flask is missing; install python3-flask.'

validator_meets_minimum() {
    local candidate=$1 version_output
    [[ -x $candidate ]] || return 1
    version_output=$("$candidate" --version 2>&1) || return 1
    python3 -c 'import re,sys; m=re.search(r"(?m)^libzim\s+(\d+)\.(\d+)\.(\d+)",sys.stdin.read()); sys.exit(0 if m and tuple(map(int,m.groups())) >= (9,4,0) else 1)' <<<"$version_output"
}

validator_path=/usr/local/lib/cyberdeck/tools/zimcheck
if [[ -e $validator_path || -L $validator_path ]]; then
    validator_meets_minimum "$validator_path" ||
        die "The existing $validator_path is not a usable libzim 9.4.0-or-newer validator; preserve and review it before replacing."
elif system_validator=$(command -v zimcheck) && validator_meets_minimum "$system_validator"; then
    : # The system validator is already compatible.
elif (( offline )); then
    die 'Offline installation needs zimcheck with libzim 9.4.0 or newer at /usr/local/lib/cyberdeck/tools/zimcheck.'
else
    for command in curl tar md5sum; do
        command -v "$command" >/dev/null || die "Missing $command; install it before installing the standalone ZIM validator."
    done
    case "$(uname -m)" in
        x86_64) validator_archive=zim-tools_linux-x86_64-3.8.0.tar.gz ;;
        # The upstream 3.8.0 ARM64 archive does not match its published MD5.
        # Keep ARM64 on the last verified release until upstream republishes it.
        aarch64) validator_archive=zim-tools_linux-aarch64-3.7.0.tar.gz ;;
        *) die 'No pinned standalone zimcheck build is available for this CPU architecture.' ;;
    esac
    validator_work=$(mktemp -d /tmp/cyberdeck-zimcheck.XXXXXXXX)
    trap 'rm -rf -- "$validator_work"' EXIT
    validator_source=https://download.openzim.org/release/zim-tools
    curl --proto '=https' --proto-redir '=https' --fail --location \
        "$validator_source/$validator_archive" -o "$validator_work/$validator_archive"
    curl --proto '=https' --proto-redir '=https' --fail --location \
        "$validator_source/$validator_archive.md5" -o "$validator_work/$validator_archive.md5"
    (cd "$validator_work" && md5sum --check "$validator_archive.md5") ||
        die 'The upstream zim-tools archive did not match its published checksum.'
    if tar -tzf "$validator_work/$validator_archive" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
        die 'The upstream zim-tools archive contains an unsafe path.'
    fi
    mkdir "$validator_work/unpacked"
    tar --no-same-owner --no-same-permissions -xzf "$validator_work/$validator_archive" \
        -C "$validator_work/unpacked"
    mapfile -t validator_candidates < <(find "$validator_work/unpacked" -type f -name zimcheck -print)
    ((${#validator_candidates[@]} == 1)) || die 'Expected exactly one zimcheck binary in the pinned upstream archive.'
    validator_meets_minimum "${validator_candidates[0]}" ||
        die 'The pinned upstream zimcheck does not report libzim 9.4.0 or newer.'
    install -d -o root -g root -m 0755 "${validator_path%/*}"
    install -o root -g root -m 0755 "${validator_candidates[0]}" "$validator_path"
    "$validator_path" --version
    rm -rf -- "$validator_work"
    trap - EXIT
fi

if getent passwd cyberdeck >/dev/null; then
    service_uid=$(id -u cyberdeck)
    service_shell=$(getent passwd cyberdeck | cut -d: -f7)
    if (( service_uid >= 1000 )) || [[ $service_shell != /usr/sbin/nologin ]]; then
        die 'The login username cyberdeck is reserved for the Hub service account. Reinstall Debian with another administrator username, such as operator.'
    fi
else
    useradd --system --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin cyberdeck
fi
[[ $(id -u cyberdeck) != 0 ]] || die 'Invalid service account.'
getent group cyberdeck-tls >/dev/null || groupadd --system cyberdeck-tls
usermod -a -G cyberdeck-tls cyberdeck

install -d -o root -g root -m 0755 /usr/local/lib/cyberdeck
install -d -o root -g root -m 0755 /usr/local/lib/cyberdeck/assets/hub
install -d -o root -g root -m 0755 /usr/local/lib/cyberdeck/profiles
install -d -o root -g root -m 0755 /usr/local/lib/cyberdeck/app
install -d -o root -g root -m 0755 /usr/local/lib/cyberdeck/app/static \
    /usr/local/lib/cyberdeck/app/templates /usr/local/lib/cyberdeck/app/translations
install -d -o cyberdeck -g cyberdeck -m 0755 "$data_root" "$data_root/zim" "$data_root/public"
install -d -o cyberdeck -g cyberdeck -m 0700 "$data_root/private"
if [[ $root_device != "$home_device" && ! -e $home_probe ]]; then
    install -d -o root -g root -m 0555 "$home_probe"
fi
install -d -o root -g cyberdeck-tls -m 0750 /etc/cyberdeck /etc/cyberdeck/tls
install -o root -g root -m 0644 "$app_source/webapp.py" "$app_source/library.py" \
    "$app_source/kiwix_https.py" "$app_source/cyberchef_server.py" \
    /usr/local/lib/cyberdeck/app/
install -o root -g root -m 0644 "$app_source/legacy_card_translations.json" \
    /usr/local/lib/cyberdeck/app/legacy_card_translations.json
install -o root -g root -m 0644 "$app_source"/templates/*.html /usr/local/lib/cyberdeck/app/templates/
install -o root -g root -m 0644 "$app_source"/static/* /usr/local/lib/cyberdeck/app/static/
install -o root -g root -m 0644 "$app_source"/translations/*.json /usr/local/lib/cyberdeck/app/translations/
install -o root -g root -m 0644 "$starter_asset" \
    /usr/local/lib/cyberdeck/assets/hub/library-startup.html
install -o root -g root -m 0644 "$starter_profile" \
    /usr/local/lib/cyberdeck/profiles/starter.json
if [[ -d "$profiles_source" ]]; then
    shopt -s nullglob
    profile_files=("$profiles_source"/*.json)
    if ((${#profile_files[@]})); then
        install -o root -g root -m 0644 "${profile_files[@]}" /usr/local/lib/cyberdeck/profiles/
    fi
    shopt -u nullglob
fi
install -o root -g root -m 0755 "$app_source/serve-kiwix.sh" /usr/local/lib/cyberdeck/serve-kiwix.sh
if [[ ! -e /usr/local/lib/cyberdeck/starter.json ]]; then
    install -o root -g root -m 0644 "$empty_manifest" /usr/local/lib/cyberdeck/starter.json
fi

if [[ ! -s /etc/cyberdeck/session.key ]]; then
    umask 077
    openssl rand -out /etc/cyberdeck/session.key 48
    chown root:cyberdeck /etc/cyberdeck/session.key
    chmod 0640 /etc/cyberdeck/session.key
fi
if [[ ! -s /etc/cyberdeck/tls/ca.key && ! -s /etc/cyberdeck/tls/ca.crt ]]; then
    umask 077
    openssl req -x509 -newkey rsa:3072 -nodes -days 3650 \
        -keyout /etc/cyberdeck/tls/ca.key -out /etc/cyberdeck/tls/ca.crt \
        -subj '/CN=Cyberdeck Local Library CA' \
        -addext 'basicConstraints=critical,CA:TRUE' \
        -addext 'keyUsage=critical,keyCertSign,cRLSign'
    chown root:root /etc/cyberdeck/tls/ca.key
    chmod 0600 /etc/cyberdeck/tls/ca.key
    chmod 0644 /etc/cyberdeck/tls/ca.crt
elif [[ ! -s /etc/cyberdeck/tls/ca.key || ! -s /etc/cyberdeck/tls/ca.crt ]]; then
    die 'A partial local CA already exists. Preserve it and repair the pair manually before retrying.'
fi
if [[ ! -s /etc/cyberdeck/tls/server.key && ! -s /etc/cyberdeck/tls/server.crt ]]; then
    umask 077
    openssl req -new -newkey rsa:2048 -nodes \
        -keyout /etc/cyberdeck/tls/server.key -out /etc/cyberdeck/tls/server.csr \
        -subj "/CN=$hostname_expected"
    san="DNS:$hostname_expected,DNS:$hostname_expected.local,DNS:$hostname_expected.lan,IP:127.0.0.1"
    printf 'subjectAltName=%s\nextendedKeyUsage=serverAuth\n' "$san" > /etc/cyberdeck/tls/server.ext
    openssl x509 -req -in /etc/cyberdeck/tls/server.csr -CA /etc/cyberdeck/tls/ca.crt \
        -CAkey /etc/cyberdeck/tls/ca.key -CAcreateserial -out /etc/cyberdeck/tls/server.crt \
        -days 825 -sha256 -extfile /etc/cyberdeck/tls/server.ext
    rm -f /etc/cyberdeck/tls/server.csr /etc/cyberdeck/tls/server.ext /etc/cyberdeck/tls/ca.srl
    chown root:cyberdeck-tls /etc/cyberdeck/tls/server.key /etc/cyberdeck/tls/server.crt
    chmod 0640 /etc/cyberdeck/tls/server.key
    chmod 0644 /etc/cyberdeck/tls/server.crt
elif [[ ! -s /etc/cyberdeck/tls/server.key || ! -s /etc/cyberdeck/tls/server.crt ]]; then
    die 'A partial server certificate already exists. Preserve it and repair the pair manually before retrying.'
fi
openssl verify -CAfile /etc/cyberdeck/tls/ca.crt \
    -verify_hostname "$hostname_expected.local" /etc/cyberdeck/tls/server.crt >/dev/null ||
    die 'The existing server certificate does not match this library hostname.'
chown root:cyberdeck-tls /etc/cyberdeck/tls/server.key /etc/cyberdeck/tls/server.crt
chmod 0640 /etc/cyberdeck/tls/server.key
chmod 0644 /etc/cyberdeck/tls/server.crt
chown root:cyberdeck /etc/cyberdeck/session.key
chmod 0640 /etc/cyberdeck/session.key
cat > /etc/cyberdeck/environment <<EOF
CYBERDECK_ROOT=$data_root
CYBERDECK_PRIVATE=$data_root/private
CYBERDECK_DATA_MOUNT=$data_mount
CYBERDECK_HOME_MOUNT=$home_mount_value
CYBERDECK_SESSION_KEY_FILE=/etc/cyberdeck/session.key
CYBERDECK_CA_CERT_FILE=/etc/cyberdeck/tls/ca.crt
CYBERDECK_HOSTNAME=$hostname_expected.local
CYBERDECK_RUNTIME_MODE=headless
EOF
chown root:root /etc/cyberdeck/environment
chmod 0644 /etc/cyberdeck/environment

sed -e "s|@CYBERDECK_ROOT@|$data_root|g" \
    -e "s|@CYBERDECK_HOME_PROBE_BIND@|$home_probe_bind|g" \
    "$service_source/cyberdeck-web.service" \
    > /etc/systemd/system/cyberdeck-web.service
sed "s|@CYBERDECK_ROOT@|$data_root|g" "$service_source/cyberdeck-kiwix.service" \
    > /etc/systemd/system/cyberdeck-kiwix.service
install -o root -g root -m 0644 "$service_source/cyberdeck-redirect.service" \
    /etc/systemd/system/cyberdeck-redirect.service
install -o root -g root -m 0644 "$service_source/cyberdeck-firewall.service" \
    /etc/systemd/system/cyberdeck-firewall.service
install -o root -g root -m 0755 "$repo_root/scripts/debian/storage-helper.py" \
    /usr/local/lib/cyberdeck/storage-helper.py
install -o root -g root -m 0755 "$repo_root/scripts/debian/deploy-helper.py" \
    /usr/local/lib/cyberdeck/deploy-helper.py
install -o root -g root -m 0755 "$repo_root/scripts/debian/admin-helper.py" \
    /usr/local/lib/cyberdeck/admin-helper.py
install -o root -g root -m 0755 "$repo_root/scripts/debian/wifi-diagnostics.py" \
    /usr/local/bin/cyberdeck-wifi-diagnostics
install -o root -g root -m 0644 "$repo_root/scripts/debian/host_identity.py" \
    /usr/local/lib/cyberdeck/host_identity.py
install -o root -g root -m 0755 "$repo_root/scripts/debian/http-redirect.py" \
    /usr/local/lib/cyberdeck/http-redirect.py
install -d -o root -g root -m 0755 /etc/NetworkManager/dnsmasq-shared.d
install -o root -g root -m 0644 "$repo_root/config/debian/cyberdeck-hotspot-dns.conf" \
    /etc/NetworkManager/dnsmasq-shared.d/cyberdeck.conf
install -o root -g root -m 0644 "$repo_root/config/debian/systemd/cyberdeck-hotspot-autostart.service" \
    /etc/systemd/system/cyberdeck-hotspot-autostart.service
install -o root -g root -m 0644 "$repo_root/config/debian/systemd/cyberdeck-hotspot-autostart.timer" \
    /etc/systemd/system/cyberdeck-hotspot-autostart.timer
install -d -o root -g root -m 0755 /etc/systemd/sleep.conf.d /etc/systemd/logind.conf.d
install -o root -g root -m 0644 "$sleep_source" /etc/systemd/sleep.conf.d/90-cyberdeck.conf
install -o root -g root -m 0644 "$logind_source" /etc/systemd/logind.conf.d/90-cyberdeck.conf
install -o root -g root -m 0644 "$service_source/cyberdeck-storage-migration.service" \
    /etc/systemd/system/cyberdeck-storage-migration.service
install -o root -g root -m 0644 "$service_source/cyberdeck-storage-initialize.service" \
    /etc/systemd/system/cyberdeck-storage-initialize.service
install -o root -g root -m 0644 "$service_source/cyberdeck-storage-existing.service" \
    /etc/systemd/system/cyberdeck-storage-existing.service
install -o root -g root -m 0644 "$service_source/cyberdeck-storage-recovery.service" \
    /etc/systemd/system/cyberdeck-storage-recovery.service
install -o root -g root -m 0644 "$service_source/cyberdeck-storage-boot-recovery.service" \
    /etc/systemd/system/cyberdeck-storage-boot-recovery.service
install -o root -g root -m 0644 "$repo_root/config/debian/tmpfiles.d/cyberdeck-storage.conf" \
    /etc/tmpfiles.d/cyberdeck-storage.conf
systemd-tmpfiles --create /etc/tmpfiles.d/cyberdeck-storage.conf
chown root:root /etc/systemd/system/cyberdeck-web.service /etc/systemd/system/cyberdeck-kiwix.service
chmod 0644 /etc/systemd/system/cyberdeck-web.service /etc/systemd/system/cyberdeck-kiwix.service
printf '%s\n' \
    'cyberdeck ALL=(root) NOPASSWD: /usr/local/lib/cyberdeck/storage-helper.py, /usr/bin/systemctl restart cyberdeck-kiwix.service, /usr/bin/systemctl reboot, /usr/bin/systemctl poweroff, /usr/local/lib/cyberdeck/admin-helper.py hotspot-status, /usr/local/lib/cyberdeck/admin-helper.py hotspot-password, /usr/local/lib/cyberdeck/admin-helper.py hotspot-configure, /usr/local/lib/cyberdeck/admin-helper.py hotspot-start, /usr/local/lib/cyberdeck/admin-helper.py hotspot-stop, /usr/local/lib/cyberdeck/admin-helper.py hotspot-module-enable, /usr/local/lib/cyberdeck/admin-helper.py hotspot-module-disable, /usr/local/lib/cyberdeck/admin-helper.py hostname-status, /usr/local/lib/cyberdeck/admin-helper.py hostname-configure, /usr/local/lib/cyberdeck/admin-helper.py cyberchef-status, /usr/local/lib/cyberdeck/admin-helper.py cyberchef-enable, /usr/local/lib/cyberdeck/admin-helper.py cyberchef-disable, /usr/local/lib/cyberdeck/admin-helper.py firewall-status, /usr/local/lib/cyberdeck/admin-helper.py firewall-enable, /usr/local/lib/cyberdeck/admin-helper.py firewall-disable' \
    > /etc/sudoers.d/cyberdeck-web
chown root:root /etc/sudoers.d/cyberdeck-web
chmod 0440 /etc/sudoers.d/cyberdeck-web
visudo -cf /etc/sudoers.d/cyberdeck-web >/dev/null
runuser -u cyberdeck -- sudo -n /usr/local/lib/cyberdeck/admin-helper.py firewall-status >/dev/null ||
    die 'The installed web-service sudoers allowlist cannot run the firewall status helper.'

systemctl daemon-reload
systemctl disable --now sleep.target suspend.target hibernate.target hybrid-sleep.target 2>/dev/null || true
systemctl enable avahi-daemon cyberdeck-storage-boot-recovery cyberdeck-web cyberdeck-kiwix cyberdeck-redirect
systemctl enable --now cyberdeck-hotspot-autostart.timer
systemctl restart avahi-daemon cyberdeck-web cyberdeck-redirect
if compgen -G "$data_root/zim/*.zim" >/dev/null; then
    systemctl restart cyberdeck-kiwix
else
    systemctl stop cyberdeck-kiwix 2>/dev/null || true
fi
if (( ! offline )); then
    for directory in /opt/cyberdeck /opt/cyberdeck/modules; do
        [[ ! -L $directory ]] || die "Refusing symlinked CyberChef directory: $directory"
    done
    install -d -o root -g root -m 0755 /opt/cyberdeck /opt/cyberdeck/modules
    if python3 "$repo_root/scripts/debian/admin-helper.py" cyberchef-status |
        python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("installed") is True else 1)'; then
        printf '%s\n' 'CyberChef is already installed; preserving its current service state.'
    else
        python3 "$repo_root/scripts/debian/install-cyberchef.py" --apply --replace ||
            die 'CyberChef installation failed; the Hub update is incomplete. Resolve the reported issue and rerun the installer.'
        printf '%s\n' 'CyberChef installed and left disabled.'
    fi
else
    printf '%s\n' 'CyberChef installation skipped because --offline prevents downloading its pinned archive.'
fi
printf '%s\n' 'Post-install Wi-Fi readiness check (read-only):'
if ! python3 "$repo_root/scripts/debian/wifi-diagnostics.py"; then
    printf '%s\n' 'Wi-Fi diagnostics could not complete; rerun with: sudo cyberdeck-wifi-diagnostics' >&2
fi
printf '%s\n' 'Cyberdeck Hub installed in headless mode with hotspot and hostname controls.' \
    "Deployment recovery ID: $deployment_id (rollback preview: sudo python3 /usr/local/lib/cyberdeck/deploy-helper.py rollback $deployment_id $hostname_expected)" \
    "For first-time setup, open http://$hostname_expected.local/ (certificate guide; direct download: http://$hostname_expected.local/trust/ca.cer)." \
    'If .local does not resolve, use http://SERVER-IP/ (standard hotspot: http://10.42.0.1/).' \
    "Or copy the CA over SSH: scp ADMIN-USER@$hostname_expected.local:/etc/cyberdeck/tls/ca.crt . (replace ADMIN-USER with the Debian administrator username; use the server IP if needed)." \
    'Verify the SHA-256 fingerprint on this server with: sudo openssl x509 -noout -fingerprint -sha256 -in /etc/cyberdeck/tls/ca.crt.' \
    "After installing the CA, open https://$hostname_expected.local/." \
    'The first visit will ask you to create the administrator account before opening the library.' \
    'After setup, import a configuration profile from Admin > Export and import.' \
    'CyberChef is installed during online setup and starts disabled; Admin can enable it when needed.'
