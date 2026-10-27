# Cyberdeck Hub

Cyberdeck Hub is a local-first library for keeping reference material available
on a household network when the internet is unavailable. It provides subject
groups for documents and offline Kiwix libraries, and an administrator area for
managing content.

## Candidate installation

The source kit includes installer paths for existing Debian 13 amd64 and arm64
systems. It does not install Debian or repartition disks. The v0.2.0 source and
package checks are complete, but no v0.2.0 physical-target acceptance is
recorded yet; follow the runbook before relying on the candidate. Generic
arm64 support and each Raspberry Pi model require their own target checks;
passing on arm64 does not establish support for a particular Pi model.

Build a source kit on a connected computer:

```sh
python3 scripts/debian/build-kit.py --output /path/to/cyberdeck-hub-debian-kit.tar.gz
```

Transfer and extract the kit on the Debian computer. Review the
[installation and acceptance runbook](docs/runbooks/debian-install.md), then
run the installer in preview mode before applying it:

```sh
bash scripts/debian/install.sh --hostname cyberdeck
sudo bash scripts/debian/install.sh --apply --hostname cyberdeck
```

The first browser visit creates the administrator account. The generic starter
configuration is at `config/debian/starter.json`. Three optional, subject-only
starter profiles are included for Danish crisis preparedness, generic off-grid
preparedness, and a family off-grid library. They do not bundle guidance or
household data. See the [starter profile guide](docs/content/starter-profiles.md).

The current online crisis-links group is curated for a Danish household and
contains external services only. It is hidden when the Hub cannot reach the
internet. See the [online links source note](docs/content/online-crisis-links.md).

If a Wi-Fi adapter is missing from the Hotspot settings, run the diagnostic on
the Debian server:

```sh
cyberdeck-wifi-diagnostics
sudo cyberdeck-wifi-diagnostics  # also reads restricted kernel logs
```

It reports PCI wireless controllers, kernel Wi-Fi interfaces, NetworkManager
visibility, and firmware load errors. For an opt-in Debian firmware package
install, use `sudo cyberdeck-wifi-diagnostics --install-firmware`;
review apt's package prompt. Vendor-specific drivers may still need to be
installed separately. The script does not change anything unless that option
is passed.

## Optional components

CyberChef is a pinned optional module. An online full Debian install stages it
and leaves its service disabled; Admin can start or stop it later. Use
`--skip-cyberchef` or `--offline` to omit it. After staging, the static module
files remain on disk while CyberChef is stopped; the stopped service consumes
no runtime resources. Staging needs internet access, and the files use disk
space while installed.

The Docker files are an experimental preview. They are not a supported
deployment until persistence, backups, updates, restart recovery, and optional
services pass acceptance on a disposable Docker host.

## Development and scope

The parent `cyberdeck` project covers hardware experiments, offline solutions,
research, and target evidence. This repository contains the Hub product and its
supported installation path. Keep payloads, household documents, credentials,
and device-specific private details outside this repository.

From the repository root, run the workstation checks with Python 3, Flask,
Node.js, and Bash available:

```sh
python -m unittest discover -s tests
python -m unittest discover -s scripts/debian -p 'test_*.py'
node tests/test_accent.js
node tests/test_i18n.js
bash -n scripts/debian/install.sh
```

These checks use temporary data and mocks; they do not install packages or
change a host. Hardware, Debian installation, disconnected startup,
second-client, and backup/restore acceptance must be recorded separately from
source and package checks. The reviewed manual content update workflow is
documented in the [content refresh runbook](docs/runbooks/content-refresh.md).
The local v0.2.0 candidate scope and remaining release gates are in the [candidate note](docs/releases/v0-2-0-candidate.md).
