#!/usr/bin/env bash
# Configure or remove the sudo timestamp cache used by Debian deployments.
#
# Usage: configure-deploy-cache.sh [--preview|--apply|--remove]
#        [--user USER] [--timeout MINUTES]
#
# Examples:
#   bash scripts/debian/configure-deploy-cache.sh --user operator
#   sudo bash scripts/debian/configure-deploy-cache.sh --apply --user operator --timeout 60
#   sudo bash scripts/debian/configure-deploy-cache.sh --remove --user operator
#
# Parameters:
#   --preview   Validate and describe the change without modifying the host
#               (default action).
#   --apply     Write a managed sudoers drop-in after validating it with visudo.
#   --remove    Remove only this script's recognized sudoers drop-in.
#   --user      Existing Debian account to configure (example: operator). If
#               omitted, the script uses its configured default account.
#   --timeout   Sudo timestamp duration in minutes, from 1 to 1440 (default: 60).
#
# Apply and remove require root, normally via sudo. The configuration shares the
# selected user's sudo authentication timestamp across SSH sessions. It is a
# password cache only and never grants NOPASSWD access. Changes are confined to
# /etc/sudoers.d/cyberdeck-deploy-cache; unrelated sudoers files are not edited.
set -euo pipefail

readonly SUDOERS_DIR=/etc/sudoers.d
readonly SUDOERS_FILE=$SUDOERS_DIR/cyberdeck-deploy-cache
readonly MARKER='# Managed by configure-deploy-cache.sh.'

die() {
    printf '%s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage: configure-deploy-cache.sh [--apply|--remove] [--user USER] [--timeout MINUTES]

Preview is the default. Apply or remove requires root, normally through sudo.
Defaults: action=preview, timeout=60 minutes. Use --user to select the account.

Examples:
  bash scripts/debian/configure-deploy-cache.sh --user operator
  sudo bash scripts/debian/configure-deploy-cache.sh --apply --user operator --timeout 60
  sudo bash scripts/debian/configure-deploy-cache.sh --remove --user operator
EOF
}

action=preview
action_selected=0
user=cda
timeout=60
while (($#)); do
    case $1 in
        --apply|--remove|--preview)
            (( action_selected == 0 )) || die 'Choose only one of --apply, --remove, or --preview.'
            action=${1#--}
            action_selected=1
            ;;
        --user)
            (($# >= 2)) || die '--user requires a username.'
            user=$2
            shift
            ;;
        --timeout)
            (($# >= 2)) || die '--timeout requires minutes.'
            timeout=$2
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *) die "Unknown option: $1" ;;
    esac
    shift
done

[[ $user =~ ^[a-z_][a-z0-9_-]*\$?$ ]] || die "Invalid Debian account name: $user"
[[ $timeout =~ ^[0-9]+$ ]] || die 'Timeout must be a whole number of minutes.'
(( timeout >= 1 && timeout <= 1440 )) || die 'Timeout must be between 1 and 1440 minutes.'
getent passwd "$user" >/dev/null || die "Account does not exist: $user"

case $action in
    preview)
        printf 'Would configure %s for %s minutes in %s.\n' "$user" "$timeout" "$SUDOERS_FILE"
        printf 'Would share sudo authentication across SSH sessions; no host changes made.\n'
        exit 0
        ;;
    apply|remove)
        [[ $EUID == 0 ]] || die "Run with sudo to $action the sudoers configuration."
        ;;
    *) die "Unsupported action: $action" ;;
esac

command -v visudo >/dev/null || die 'visudo is required.'
[[ -d $SUDOERS_DIR && ! -L $SUDOERS_DIR ]] || die "Missing or unsafe directory: $SUDOERS_DIR"
[[ ! -e $SUDOERS_FILE || ( -f $SUDOERS_FILE && ! -L $SUDOERS_FILE ) ]] ||
    die "Refusing non-regular or symlink sudoers file: $SUDOERS_FILE"

is_managed_file() {
    [[ -f $SUDOERS_FILE ]] || return 1
    local -a lines=()
    mapfile -t lines < "$SUDOERS_FILE"
    ((${#lines[@]} == 3)) || return 1
    [[ ${lines[0]} == "$MARKER" &&
        ${lines[1]} =~ ^Defaults:[a-z_][a-z0-9_-]*\$?\ timestamp_type=global$ &&
        ${lines[2]} =~ ^Defaults:[a-z_][a-z0-9_-]*\$?\ timestamp_timeout=[0-9]+$ ]]
}

if [[ -e $SUDOERS_FILE ]] && ! is_managed_file; then
    die "$SUDOERS_FILE already exists and is not managed by this script; inspect it manually."
fi

if [[ $action == remove ]]; then
    if [[ ! -e $SUDOERS_FILE ]]; then
        printf 'No deploy-cache configuration exists; nothing to remove.\n'
        exit 0
    fi
    backup=$(mktemp "$SUDOERS_DIR/.cyberdeck-deploy-cache-backup.XXXXXX")
    cp -p -- "$SUDOERS_FILE" "$backup"
    rm -- "$SUDOERS_FILE"
    if ! visudo -c; then
        mv -f -- "$backup" "$SUDOERS_FILE"
        die 'Sudoers validation failed after removal; the previous file was restored.'
    fi
    rm -f -- "$backup"
    printf 'Removed %s. Run sudo -k in the deploy account to invalidate its current timestamp.\n' "$SUDOERS_FILE"
    exit 0
fi

candidate=$(mktemp "$SUDOERS_DIR/.cyberdeck-deploy-cache-candidate.XXXXXX")
backup=''
cleanup() {
    [[ -z $candidate || ! -e $candidate ]] || rm -f -- "$candidate"
    [[ -z $backup || ! -e $backup ]] || rm -f -- "$backup"
}
trap cleanup EXIT
{
    printf '%s\n' "$MARKER"
    printf 'Defaults:%s timestamp_type=global\n' "$user"
    printf 'Defaults:%s timestamp_timeout=%s\n' "$user" "$timeout"
} > "$candidate"
chown root:root "$candidate"
chmod 0440 "$candidate"
visudo -cf "$candidate" || die 'Candidate sudoers file did not validate; no host changes made.'

if [[ -e $SUDOERS_FILE ]]; then
    backup=$(mktemp "$SUDOERS_DIR/.cyberdeck-deploy-cache-backup.XXXXXX")
    cp -p -- "$SUDOERS_FILE" "$backup"
fi
mv -f -- "$candidate" "$SUDOERS_FILE"
candidate=''
if ! visudo -c; then
    if [[ -n $backup ]]; then
        mv -f -- "$backup" "$SUDOERS_FILE"
        backup=''
    else
        rm -f -- "$SUDOERS_FILE"
    fi
    die 'Full sudoers validation failed; the previous configuration was restored.'
fi
[[ -z $backup ]] || rm -f -- "$backup"
backup=''
printf 'Configured %s: global sudo timestamp for %s (%s minutes).\n' "$SUDOERS_FILE" "$user" "$timeout"
printf '%s\n' 'This is a password cache only; it does not grant NOPASSWD access.'
