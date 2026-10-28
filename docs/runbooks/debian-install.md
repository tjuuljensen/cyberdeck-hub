# Debian installation and acceptance

Reviewed 2026-10-27. This runbook covers Cyberdeck Hub on an existing Debian 13
amd64 or arm64 computer. The installer does not install an operating system,
partition disks, or configure a particular Raspberry Pi model. ARM64 support in
the source is not Raspberry Pi acceptance. For a new system, use the [guided
Debian USB bootstrap](bootstrap-install.md); this runbook starts with an
existing Debian installation. Docker is not a supported installation path.

## Prepare a source kit

On a connected workstation with Python 3:

```sh
python3 scripts/debian/build-kit.py --output ./cyberdeck-hub-debian-kit.tar.gz
sha256sum cyberdeck-hub-debian-kit.tar.gz > cyberdeck-hub-debian-kit.tar.gz.sha256
```

The builder normalizes archive timestamps and modes. Rebuilding from the same
source files with the same toolchain produces the same archive checksum.

Transfer the kit and checksum using trusted media. On the Debian host, verify
the checksum and extract into a new directory:

```sh
sha256sum -c cyberdeck-hub-debian-kit.tar.gz.sha256
mkdir cyberdeck-hub-source
tar -xzf cyberdeck-hub-debian-kit.tar.gz -C cyberdeck-hub-source
cd cyberdeck-hub-source
```

Copy the checksum file with the kit and verify it on Debian with
`sha256sum -c cyberdeck-hub-debian-kit.tar.gz.sha256`. Keep the original kit
until installation and recovery checks are complete.

## Preview and install

Use a short DNS-safe hostname that is unique on the local network. Preview is
the default and reports planned package, service, network, and data-root work
without applying it:

```sh
bash scripts/debian/install.sh --hostname cyberdeck
```

Review the preview and ensure the chosen data filesystem has room for selected
offline content and at least the configured reserve. Then apply the installer
with sudo:

```sh
sudo bash scripts/debian/install.sh --apply --hostname cyberdeck
```

For a disconnected installation, prepare the documented Debian package cache
on a matching Debian 13 architecture before transfer and use the installer's
`--offline` option. Do not use an unrelated package cache as proof of an
offline installation.

The installer creates the Hub and Kiwix services and a local TLS certificate.
It leaves the optional Cyberdeck firewall module disabled by default. Admin's
preflight checks for active UFW, firewalld, nftables, netfilter-persistent,
Shorewall, ferm, iptables, and ip6tables services, plus other nftables input
rules. If it finds a conflict, it disables the control and shows what it found.
It cannot detect every custom or externally managed firewall; leave the module
off and ask the person who manages the host if unsure. When enabled, it preserves
the active SSH port and Hub, DNS, and hotspot essentials. The installer installs the exact sudoers actions required to read and
change firewall state. On an older installation, a `password is required` or
`/run/sudo/ts` status error means the installed allowlist is stale; rebuild and
apply a current source kit using the steps above, then reload Admin. Do not
change `/run` permissions to work around this error. The installer does not
rewrite NetworkManager connection profiles. The first visit to
`https://cyberdeck.local/` starts administrator setup; create and store the
administrator credentials outside this repository. Install and trust the
provided local CA on each client using the certificate help page.

Useful host checks after applying:

```sh
systemctl --no-pager --full status cyberdeck-web cyberdeck-kiwix
systemctl is-enabled cyberdeck-web cyberdeck-kiwix
```

Do not treat a successful installer exit or a workstation package build as
proof of offline operation or recoverability.

## Wi-Fi adapter troubleshooting

When an adapter is missing from Hotspot settings or is listed as unavailable,
run the server-side diagnostic:

```sh
sudo cyberdeck-wifi-diagnostics
```

The report separates kernel interface detection, NetworkManager visibility,
access-point mode support, and firmware load errors. A Wi-Fi adapter can appear
in NetworkManager even when its chipset firmware is missing. Check its specific
reason and firmware status with:

```sh
nmcli -f GENERAL.STATE,GENERAL.REASON,GENERAL.NM-MANAGED,GENERAL.FIRMWARE-MISSING \
  device show WIFI-INTERFACE
sudo journalctl -k -b --no-pager | grep -i firmware
```

For example, the 3Com 3CRUSB10075 uses the ZyDAS ZD1211 chipset and the
`zd1211rw` kernel driver. If the kernel reports that it cannot load
`zd1211/zd1211_ub`, install Debian's `firmware-zd1211` package, then reconnect
the adapter or reboot:

```sh
sudo apt update
sudo apt install firmware-zd1211
```

Debian lists `firmware-zd1211` in the `non-free-firmware` component. The
package contains `zd1211/zd1211_ub` and supports the `zd1211rw` driver ([package
details](https://packages.debian.org/trixie/kernel/firmware-zd1211), [file
list](https://packages.debian.org/uk/trixie/all/firmware-zd1211/filelist)). The
general `firmware-linux` package did not provide this file on the observed
Cyberdeck, so prefer the package indicated by the missing firmware path.

On 2026-10-27, the reported Cyberdeck confirmed that installing
`firmware-zd1211` resolved the adapter issue. For future cases, confirm
`GENERAL.FIRMWARE-MISSING` is `no`, NetworkManager no longer reports the device
as `unavailable`, and the Hotspot selector allows it to be selected. The
diagnostic currently maps the ZD1211 firmware path to its Debian package; other
chipset firmware errors still need package-specific identification.

## Content and optional services

The starter configuration is `config/debian/starter.json`. Admin import accepts
reviewed configuration files and starts selected Internet PDF or ZIM
acquisition after the configuration is saved. PDF status is recorded per file;
failed downloads can be retried. A recorded source URL is provenance, not a
copy of the source file.

CyberChef is pinned and staged automatically during an online full Debian
install. Its systemd service is left disabled so it uses no CPU until an
administrator enables it from Admin > CyberChef. Use `--skip-cyberchef` to
omit the module; `--offline` also skips staging. The module files use disk
space, and staging needs internet access. If staging fails, the Hub install
continues and the warning is printed by the installer. Review storage and
outbound network needs before enabling it on a low-resource computer.

Scheduled refresh of Wikipedia, maps, or other content is not yet a supported
Hub workflow. Until a staged, verified update and rollback path is available,
review and apply content updates manually. Keep the current working copy until
the replacement has been verified.

## Backup and restore

There are two different backup scopes:

- An exported Hub configuration preserves catalogue metadata and source links.
  It does not package the remote PDF files those links point to.
- The Debian recovery backup copies the configured data root. Files that were
  successfully downloaded before the backup, including acquired PDFs and
  their acquisition records, are copied and checksummed. A URL for a file that
  was never downloaded cannot restore that file without network access.

The recovery backup requires a mounted, identifiable physical disk separate
from the library data disk, a completed recovery-package cache, and sufficient
free space. Run it from the source kit as root, first checking that the mount
is the intended backup disk:

```sh
findmnt --target /mnt/backup
python3 app/library.py backup --root /srv/cyberdeck --mount /mnt/backup
```

Keep installation media and any private household material protected.
Do not describe a backup as recoverable until its checksum verification and a
disconnected restore rehearsal both succeed on a separate destination.

Before restoring, verify the backup inventory. Restore into a new destination
that does not exist; the command verifies the inventory before copying and
checks restored content afterward:

```sh
python3 app/library.py verify-bundle --bundle /mnt/backup/cyberdeck-YYYYMMDDTHHMMSSffffffZ
python3 app/library.py restore --bundle /mnt/backup/cyberdeck-YYYYMMDDTHHMMSSffffffZ --destination /srv/cyberdeck-restore
python3 app/library.py verify --root /srv/cyberdeck-restore
```

Replace the example bundle name with the actual directory. Package and service
restore is separate. Preserve the current data tree and keep it until the
restored Hub, documents, and Kiwix libraries have passed the checks below.

## Release acceptance record

Record each check with the Hub version, date, hardware/architecture, and the
result. A source test or package inspection is not a target observation.

- Install, upgrade, rollback, and recovery on at least two physical Debian 13
  amd64 computers.
- Before advertising generic arm64 support, complete the same lifecycle,
  offline-startup, backup/restore, and resource checks on at least one physical
  Debian 13 arm64 target. Record its exact model and architecture. This does not
  establish support for a Raspberry Pi model without model-specific checks.
- Cold-start the Hub without internet; verify local pages and acquired files
  from a second client on the LAN or device hotspot.
- Import a profile containing successful and deliberately unavailable PDF
  sources; confirm per-file status, visible failure detail, and retry behavior.
- Confirm the three optional starter profiles are present in the install kit;
  preview each in settings-only mode and verify no content downloads start.
- Confirm a profile export contains source links but not downloaded payloads;
  confirm a full recovery backup includes acquired PDF payloads and hashes.
- Complete checksum verification and a disconnected restore rehearsal on a
  separate data destination.
- Measure idle and active memory, storage use, and responsiveness with
  CyberChef disabled and enabled.

No physical target acceptance is implied by this source runbook. Keep open
target-only checks open until dated evidence is recorded.
