#!/usr/bin/env bash
# Offer a local first-login Cyberdeck installation; applying changes needs sudo.
set -euo pipefail

state_dir=/var/lib/cyberdeck-bootstrap
source_dir=$state_dir/source
archive=$state_dir/source.tar.gz
installer=$source_dir/scripts/debian/install.sh
cyberchef_installer=$source_dir/scripts/debian/install-cyberchef.py
admin_helper=$source_dir/scripts/debian/admin-helper.py
host=${CYBERDECK_INSTALL_HOSTNAME:-cyberdeck}

say() { printf '%s\n' "$*"; }
fail() { say "Cyberdeck setup: $*" >&2; exit 1; }

login_home=${HOME:-/root}
if (( EUID == 0 )) && [[ -n ${SUDO_USER:-} ]]; then
    login_record=$(getent passwd "$SUDO_USER" || true)
    if [[ -n $login_record ]]; then
        IFS=: read -r _ _ _ _ _ login_home _ <<< "$login_record"
    fi
fi
skip_marker=$login_home/.cache/cyberdeck-install-skipped

[[ -d $state_dir && -f $state_dir/pending ]] || exit 0
[[ ! -e $state_dir/complete ]] || exit 0
if [[ ${1:-} != '' && ${1:-} != --retry && ${1:-} != --confirmed ]]; then
    fail 'usage: cyberdeck-firstboot-install [--retry]'
fi
if [[ ${1:-} == --confirmed && $EUID != 0 ]]; then
    fail 'internal confirmation mode requires root; run the command without --confirmed.'
fi
if [[ -e $skip_marker && ${1:-} != --retry ]]; then
    exit 0
fi
[[ -t 0 && -t 1 ]] || exit 0

if [[ ${1:-} == --retry && $EUID != 0 ]]; then
    command -v sudo >/dev/null || fail 'sudo is unavailable; log in as an administrator and run this script with root privileges.'
    exec sudo -- "$0" --retry
fi
if [[ -e $skip_marker ]]; then
    rm -f -- "$skip_marker"
fi

if [[ ${1:-} != --confirmed ]]; then
    read -r -p 'Start the Cyberdeck installation now? [y/N] ' answer || exit 0
    case "$answer" in
        y|Y|yes|YES) ;;
        *)
            install -d -m 0700 "${skip_marker%/*}"
            touch "$skip_marker"
            say "Skipped. Retry later with: sudo $0 --retry"
            exit 0
            ;;
    esac
    if (( EUID != 0 )); then
        command -v sudo >/dev/null || fail 'sudo is unavailable; log in as an administrator and run this script with root privileges.'
        exec sudo -- "$0" --confirmed
    fi
fi

if [[ ! -f $installer ]]; then
    [[ -f $archive ]] || fail "the staged install kit is missing; restore $archive and retry."
    install -d -o root -g root -m 0755 "$source_dir"
    tar --no-same-owner --no-same-permissions -xzf "$archive" -C "$source_dir" ||
        fail 'could not unpack the staged install kit; the archive was retained for recovery.'
fi
[[ -f $installer && ! -L $installer ]] || fail 'the staged Hub installer is missing or unsafe.'
[[ -f $admin_helper && ! -L $admin_helper ]] || fail 'the staged admin helper is missing or unsafe.'
for action in hotspot-module-enable hotspot-module-disable cyberchef-status cyberchef-enable cyberchef-disable firewall-status firewall-enable firewall-disable; do
    grep -Fq "'$action':" "$admin_helper" ||
        fail "the staged admin helper is outdated (missing $action); rebuild the source kit."
done

account=$(getent passwd cyberdeck || true)
if [[ -n $account ]]; then
    IFS=: read -r account_name _ account_uid _ account_home _ account_shell <<< "$account"
    if [[ $account_name != cyberdeck || $account_home != /nonexistent ||
          $account_shell != /usr/sbin/nologin || ! $account_uid =~ ^[0-9]+$ ]] ||
       (( account_uid >= 1000 )); then
        fail 'the login username cyberdeck is reserved for the Hub service. Reinstall Debian with another administrator username, such as operator, then retry.'
    fi
fi

say 'Cyberdeck Hub installation is ready. A working internet connection is needed to install Debian packages.'
say 'Previewing the Hub installation; this preview does not change the host.'
bash "$installer" --hostname "$host" || fail 'the installer preview failed; resolve the reported issue and retry.'
read -r -p 'Apply the previewed Cyberdeck installation? Type APPLY to continue: ' confirmation || exit 0
[[ $confirmation == APPLY ]] || {
    install -d -m 0700 "${skip_marker%/*}"
    touch "$skip_marker"
    say "No changes applied. Retry later with: sudo $0 --retry"
    exit 0
}

if ! bash "$installer" --apply --hostname "$host"; then
    fail 'the apply step failed. The staged source remains available; fix the reported issue and retry.'
fi
install -o root -g root -m 0755 "$admin_helper" /usr/local/lib/cyberdeck/admin-helper.py
visudo -cf /etc/sudoers.d/cyberdeck-web >/dev/null ||
    fail 'the installed sudoers allowlist is invalid; inspect /etc/sudoers.d/cyberdeck-web.'
for action in hotspot-module-enable hotspot-module-disable cyberchef-status cyberchef-enable cyberchef-disable firewall-status firewall-enable firewall-disable; do
    grep -Fq "/usr/local/lib/cyberdeck/admin-helper.py $action" /etc/sudoers.d/cyberdeck-web ||
        fail "the sudoers allowlist is missing $action; rerun the installer from the current source kit."
done
say 'Installed the current privileged helper and validated its sudoers allowlist.'

read -r -p 'Install optional CyberChef on HTTPS port 8445? [Y/n] ' cyberchef_choice ||
    fail 'could not read the CyberChef choice; rerun setup to continue.'
case "$cyberchef_choice" in
    n|N|no|NO|No)
        say 'Skipping CyberChef. It can be installed later from the staged source kit.'
        ;;
    *)
        [[ -f $cyberchef_installer && ! -L $cyberchef_installer ]] ||
            fail 'the staged CyberChef installer is missing or unsafe; restore the source kit and retry.'
        say 'Previewing the pinned CyberChef installation; this preview does not change the host.'
        python3 "$cyberchef_installer" || fail 'the CyberChef preview failed; resolve the reported issue and retry.'
        read -r -p 'Apply the previewed CyberChef installation? Type APPLY to continue: ' cyberchef_confirmation ||
            fail 'could not read the CyberChef confirmation; rerun setup to continue.'
        if [[ $cyberchef_confirmation == APPLY ]]; then
            python3 "$cyberchef_installer" --apply ||
                fail 'CyberChef installation failed. The staged source remains available; fix the reported issue and retry.'
            say "Open https://$host.local:8445/ from a client that trusts the Cyberdeck CA."
        else
            say 'CyberChef was not installed. It can be installed later from the staged source kit.'
        fi
        ;;
esac

touch "$state_dir/complete"
rm -f -- "$state_dir/pending" "$skip_marker"
say 'Cyberdeck Hub installation completed.'
say "For first-time client setup, open http://$host.local/ and download the CA certificate."
say "Direct CA download: http://$host.local/trust/ca.cer"
say 'If .local does not resolve, use http://SERVER-IP/ on the same network (standard hotspot: http://10.42.0.1/).'
say "Or copy it over SSH: scp ADMIN-USER@$host.local:/etc/cyberdeck/tls/ca.crt . (replace ADMIN-USER; use the server IP if .local does not resolve)."
say 'Confirm the certificate SHA-256 fingerprint on this server with: sudo openssl x509 -noout -fingerprint -sha256 -in /etc/cyberdeck/tls/ca.crt'
say "After trusting the CA, open https://$host.local/"
