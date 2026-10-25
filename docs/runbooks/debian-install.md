# Debian installation and acceptance

Reviewed 2026-10-25. This runbook covers Cyberdeck Hub on an existing Debian 13
amd64 or arm64 computer. The installer does not install an operating system,
partition disks, or configure a particular Raspberry Pi model. ARM64 support in
the source is not Raspberry Pi acceptance. Docker remains an experimental
preview.

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
It does not rewrite network profiles or firewall rules. The first visit to
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
