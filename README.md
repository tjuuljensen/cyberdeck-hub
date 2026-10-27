# Cyberdeck Hub

Cyberdeck Hub is a local-first library for keeping reference material available
to a household over a local network, including when internet access is down. It
organizes documents and offline Kiwix libraries by subject and provides an
administrator area for managing content, modules, and the server.

## Choose an installation path

Cyberdeck Hub is designed for Debian 13. Choose the path that fits your starting
point:

| Starting point | Use this path |
| --- | --- |
| You are preparing a new Cyberdeck computer | Use the guided Debian USB bootstrap. It prepares custom Debian install media with the Hub source kit and first-boot setup. See the [bootstrap install guide](docs/runbooks/bootstrap-install.md). |
| Debian 13 is already installed | Start at the existing-system installation section in the [manual Debian install guide](docs/runbooks/debian-install.md). It covers preview, install, configuration, customization, and recovery. |
| You are developing or deploying a Hub change | Use the Windows developer deployment helper in the sibling `cyberdeck` repository. It packages a reviewed standalone Hub checkout and deploys that version to a target. See the sibling [developer deployment guide](../cyberdeck/docs/development.md) and [Debian target runbook](../cyberdeck/docs/runbooks/debian-install.md). |

The install guide identifies supported Debian versions and architectures and
separates source/package checks from physical-target acceptance. Generic ARM64
support does not establish support for a particular Raspberry Pi model.

## First use

After installation, open the Hub address printed by the installer, usually
`https://cyberdeck.local/`. On first visit, create the administrator account.
For a new browser or device, follow the certificate help page to verify and
trust the local certificate authority before using HTTPS.

In **Admin**, review the available configuration profiles before applying one.
Use **settings only** to preview subject and site settings without starting
content downloads. A full import can queue acquisitions from its listed
sources. Review the import preview and available storage first.

To add material, use **Admin > Documents** for reference files and **Admin >
Kiwix libraries** for ZIM archives. Keep source, edition, publication date, and
reuse terms with selected content. Hub stores acquired files locally; an
internet source URL alone is not an offline copy.

## Daily use and recovery

- Open a subject card to find related documents and Kiwix libraries. Hub search
  searches catalogue metadata; use the Kiwix search bar to search inside ZIM
  libraries.
- Online Source and RSS cards require internet access. RSS is a reader, not an
  emergency alert or notification service.
- Check available storage in **Admin > System** before acquiring large files.
- Export configuration for metadata and source links. It does not include
  downloaded PDF payloads. Use the Debian recovery backup for acquired content,
  and perform a restore rehearsal before relying on it.
- Keep credentials, household records, and downloaded reference payloads out
  of Git. Store administrator credentials separately from the server.

See the [Debian install guide](docs/runbooks/debian-install.md) for detailed
service behavior, custom data roots, offline installation, optional modules,
backup and restore, and troubleshooting. The [content refresh runbook](docs/runbooks/content-refresh.md)
covers the reviewed manual update workflow.

## Profiles and optional modules

The install includes an empty generic starter configuration and optional
profiles. Profiles define selected subjects and content sources; review their
scope and import preview before applying. See the [profile guide](docs/content/starter-profiles.md)
for the naming and content-selection policy.

CyberChef is an optional Debian module. Online installation can stage the
pinned files while leaving the service disabled; Admin can enable it later.
Staging requires internet access and consumes disk space. The Hotspot is also
an optional host module. A managed nftables firewall can be enabled in Admin
when the host has no competing firewall manager or input policy. It is disabled
by default. Read the install guide before changing host network or firewall
settings, especially when administering the host remotely.

Docker is not currently a supported installation path. Use the Debian guide.

## Development and project boundaries

This repository is the source of truth for the Hub application, its profiles,
and user-facing bootstrap. The sibling `cyberdeck` repository owns hardware
research, target evidence, and the Windows developer deployment helper. The
developer helper must use a reviewed checkout of this standalone repository,
not a nested copy.

For architecture and migration decisions, see the [architecture review](docs/architecture-review.md).
The [v0.2.0 candidate note](docs/releases/v0-2-0-candidate.md) records release
scope and remaining acceptance gates.
