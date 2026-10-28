#!/usr/bin/env bash
# Build a Debian 13 Cyberdeck installer ISO and, optionally, write it to USB.
#
# Examples:
#   scripts/debian/create-usb-linux.sh --iso debian-13.1.0-amd64-netinst.iso \
#     --checksums SHA512SUMS --output-dir ./cyberdeck-media
#   sudo scripts/debian/create-usb-linux.sh --iso debian-13.1.0-amd64-netinst.iso \
#     --checksums SHA512SUMS --output-dir ./cyberdeck-media \
#     --write --device /dev/sdX
#
# Parameters:
#   --iso         Official Debian 13 amd64 netinst ISO to customize.
#   --checksums   Debian SHA512SUMS file containing that ISO's SHA-512 entry.
#   --output-dir  Directory for the generated installer ISO and build artifacts.
#   --write       Also write the generated ISO to a removable USB disk. Omitted
#                 by default; without it, no disk is written.
#   --device      Whole USB disk (for example /dev/sdX), required with --write.
#
# The ISO and checksum file must match Debian's official amd64 iso-cd release.
# Writing requires root, an explicitly selected removable whole disk with all
# partitions unmounted, and typing the exact erase confirmation. This erases all
# data on that device. The generated ISO is not overwritten if it already exists.
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd -- "$script_dir/../.." && pwd)
iso=''
checksums=''
output_dir=''
device=''
write_media=0

usage() {
    cat <<'EOF'
Build a Cyberdeck Debian 13 installer ISO. No disk is written unless --write is given.

  scripts/debian/create-usb-linux.sh --iso debian-13.x-amd64-netinst.iso \
    --checksums SHA512SUMS --output-dir ./cyberdeck-media
  scripts/debian/create-usb-linux.sh --iso debian-13.x-amd64-netinst.iso \
    --checksums SHA512SUMS --output-dir ./cyberdeck-media --write --device /dev/sdX

The ISO and SHA512SUMS must come from Debian's official amd64 iso-cd directory.
Writing requires a removable USB disk, explicit --device, and typed erase confirmation.
EOF
}
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

while (($#)); do
    case "$1" in
        --iso) (($# >= 2)) || { usage; die '--iso requires a path.'; }; iso=$2; shift ;;
        --checksums) (($# >= 2)) || { usage; die '--checksums requires a path.'; }; checksums=$2; shift ;;
        --output-dir) (($# >= 2)) || { usage; die '--output-dir requires a path.'; }; output_dir=$2; shift ;;
        --device) (($# >= 2)) || { usage; die '--device requires a block device.'; }; device=$2; shift ;;
        --write) write_media=1 ;;
        -h|--help) usage; exit 0 ;;
        *) usage; die "Unknown option: $1" ;;
    esac
    shift
done

[[ -n $iso && -n $checksums && -n $output_dir ]] || { usage; die 'Provide --iso, --checksums and --output-dir.'; }
if (( write_media )) && [[ -z $device ]]; then
    die 'Specify the whole removable device explicitly with --device when using --write.'
fi
[[ -f $iso && ! -L $iso && -f $checksums && ! -L $checksums ]] || die 'ISO and checksum file must be regular files.'
[[ $(basename -- "$iso") =~ ^debian-13\.[0-9]+\.[0-9]+-amd64-netinst\.iso$ ]] ||
    die 'Expected an official Debian 13 amd64 netinst ISO filename.'
mkdir -p -- "$output_dir"
output_dir=$(cd -- "$output_dir" && pwd)
output_iso="$output_dir/cyberdeck-debian-installer.iso"
[[ ! -e $output_iso && ! -L $output_iso ]] || die "Refusing to overwrite $output_iso."

checksum_line=$(awk -v name="$(basename -- "$iso")" '$2 == name || $2 == "*" name { print $1 "  " name }' "$checksums")
[[ $checksum_line =~ ^[0-9A-Fa-f]{128}[[:space:]] ]] || die 'No unique SHA-512 entry for the ISO in SHA512SUMS.'
[[ $(printf '%s\n' "$checksum_line" | wc -l) -eq 1 ]] || die 'SHA512SUMS has duplicate entries for this ISO.'
(cd -- "$(dirname -- "$iso")" && printf '%s\n' "$checksum_line" | sha512sum --check --status) ||
    die 'The Debian ISO does not match the official SHA512SUMS entry.'

for command in xorriso python3; do command -v "$command" >/dev/null || die "Missing required command: $command"; done
work=$(mktemp -d "${TMPDIR:-/tmp}/cyberdeck-usb.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
xorriso -osirrox on -indev "$iso" \
    -extract /boot/grub/grub.cfg "$work/grub.cfg" \
    -extract /isolinux/txt.cfg "$work/txt.cfg" >/dev/null 2>&1 ||
    die 'Could not extract the expected Debian BIOS and UEFI boot configurations.'
python3 "$repo_root/scripts/debian/build_usb_media.py" \
    --repo-root "$repo_root" --iso "$iso" --grub-config "$work/grub.cfg" \
    --isolinux-config "$work/txt.cfg" --output-dir "$output_dir"
stage="$output_dir/overlay"

xorriso -indev "$iso" -outdev "$output_iso" \
    -map "$stage/preseed.cfg" /preseed.cfg \
    -map "$stage/cyberdeck-install-kit.tar.gz" /cyberdeck-install-kit.tar.gz \
    -map "$stage/cyberdeck-firstboot-install.sh" /cyberdeck-firstboot-install.sh \
    -map "$stage/cyberdeck-firstboot-profile.sh" /cyberdeck-firstboot-profile.sh \
    -map "$stage/cyberdeck-media-manifest.json" /cyberdeck-media-manifest.json \
    -map "$stage/boot/grub/grub.cfg" /boot/grub/grub.cfg \
    -map "$stage/isolinux/txt.cfg" /isolinux/txt.cfg \
    -boot_image any replay -commit >/dev/null || die 'xorriso could not create the custom installer ISO.'

xorriso -indev "$output_iso" -report_el_torito plain >"$work/el-torito.txt" 2>&1 || die 'Could not verify ISO boot records.'
grep -Eqi 'BIOS' "$work/el-torito.txt" || die 'The custom ISO is missing the BIOS boot image.'
grep -Eqi 'UEFI|EFI' "$work/el-torito.txt" || die 'The custom ISO is missing the UEFI boot image.'
xorriso -osirrox on -indev "$output_iso" -extract /preseed.cfg "$work/extracted-preseed.cfg" >/dev/null 2>&1 ||
    die 'The preseed was not present in the generated ISO.'
cmp -s "$stage/preseed.cfg" "$work/extracted-preseed.cfg" || die 'The embedded preseed differs from the source file.'
iso_sha512=$(sha512sum "$output_iso" | awk '{print $1}')
python3 - "$output_dir/cyberdeck-media-manifest.json" "$output_iso" "$iso_sha512" <<'PY'
import json
from pathlib import Path
import sys
manifest_path, iso_path, checksum = map(Path, sys.argv[1:])
data = json.loads(manifest_path.read_text(encoding='utf-8'))
data['custom_iso'] = iso_path.name
data['custom_iso_sha512'] = str(checksum)
manifest_path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
PY
printf 'Created %s\nSHA-512: %s\n' "$output_iso" "$iso_sha512"

if (( write_media )); then
    [[ -n $device ]] || die '--write requires an explicit --device /dev/sdX.'
    [[ -b $device ]] || die "Not a block device: $device"
    device=$(readlink -f -- "$device")
    [[ $(lsblk -dnro TYPE -- "$device") == disk ]] || die 'The target must be a whole disk, not a partition.'
    removable=$(lsblk -dnro RM -- "$device")
    transport=$(lsblk -dnro TRAN -- "$device")
    [[ $removable == 1 || $transport == usb ]] || die 'The selected disk is not identified as removable USB media.'
    [[ -z $(lsblk -nrpo MOUNTPOINT -- "$device" | sed '/^[[:space:]]*$/d') ]] ||
        die 'Unmount every partition on the selected USB disk before writing.'
    root_source=$(findmnt -n -o SOURCE /)
    root_devices=$(lsblk -s -nrpo NAME -- "$root_source" 2>/dev/null) ||
        die 'Could not identify the block devices backing the running root filesystem; refusing to write.'
    [[ -n $root_devices ]] || die 'Could not identify the block devices backing the running root filesystem; refusing to write.'
    while IFS= read -r path; do
        [[ $(readlink -f -- "$path") != "$device" ]] ||
            die 'Refusing to overwrite a disk backing the running root filesystem.'
    done <<< "$root_devices"
    lsblk -d -o NAME,MODEL,SIZE,TRAN,RM -- "$device"
    read -r -p "This erases $device. Type ERASE $device to continue: " confirmation
    [[ $confirmation == "ERASE $device" ]] || die 'Confirmation did not match; no USB data was written.'
    dd if="$output_iso" of="$device" bs=4M conv=fsync status=progress
    sync
    printf 'USB installer written to %s.\n' "$device"
fi
