# Cyberdeck Hub

Cyberdeck Hub is a local-first reference library for households, community
groups, workshops, and other small teams that want useful information available
on a local network even when internet access is unavailable. It brings selected
PDFs and offline Kiwix libraries together in a searchable catalogue, with an
administrator area for managing content and the host.

The project is designed for deliberate, curated collections rather than a
replacement for the internet or a guaranteed emergency-alert service. Choose
what to install based on how the library will be used:

- **Documents** are useful for specific local guides, checklists, and other
  reference PDFs. Choose material that is permitted to store and share, and
  keep its source and edition information with it.
- **Kiwix** serves ZIM archives such as offline encyclopedias and reference
  books. It is useful for broad collections and searching within those works,
  but archives can be large and should be refreshed deliberately when online.
- **The optional Hotspot** lets nearby devices connect directly to the Hub when
  there is no usable local Wi-Fi. It changes host networking and needs a
  suitable wireless adapter; it is unnecessary when the Hub is already
  reachable on the household LAN.
- **The optional firewall** adds a default-deny inbound policy while allowing
  Hub essentials and detected SSH access. It can reduce exposure on a dedicated
  host, but can conflict with an existing firewall or disrupt remote access.
  It is off by default; review the preflight findings and host network setup
  before enabling it. It does not replace Wi-Fi security or router firewalling.

Cyberdeck uses HTTPS with a private local certificate authority. This allows
phones and browsers to use secure connections for the Hub and its PDFs without
depending on internet access or a public hostname. Each client must trust that
local CA first. The initial setup page uses HTTP only to provide the certificate
bootstrap; HTTP itself is unencrypted, so use it only on a network you trust and
verify the certificate fingerprint before installing it. See the
[certificate setup and removal guide](docs/certificate-trust.md) for the full
steps and the issues this can cause.

## Choose an installation path

Cyberdeck Hub is designed for Debian 13. Choose the path that fits your starting
point:

| Starting point | Use this path |
| --- | --- |
| You are preparing a new Cyberdeck computer | Use the guided Debian USB bootstrap. It prepares custom Debian install media with the Hub source kit and first-boot setup. See the [bootstrap install guide](docs/runbooks/bootstrap-install.md). |
| Debian 13 is already installed | Start at the existing-system installation section in the [manual Debian install guide](docs/runbooks/debian-install.md). It covers preview, install, configuration, customization, and recovery. |
| You are developing or deploying a Hub change | Build a source-only Debian kit from this checkout with `python3 scripts/debian/build-kit.py --output ./cyberdeck-hub-debian-kit.tar.gz`, then follow the [manual Debian install guide](docs/runbooks/debian-install.md) to preview and install it on the target. |

The install guide identifies supported Debian versions and architectures and
separates source/package checks from physical-target acceptance. Generic ARM64
support does not establish support for a particular Raspberry Pi model.

## First use

After installation, connect your phone or computer to the same local network
as the Hub. For first-time setup, open `http://cyberdeck.local/` (or use the
server IP printed by the installer; the standard Cyberdeck hotspot is
`http://10.42.0.1/`). This HTTP page is only for setting up certificate trust;
do not enter passwords or use the Hub over HTTP. Download the CA certificate,
verify its SHA-256 fingerprint against the value on the server, then install it
as a trusted root certificate on the device. On iPhone, use Safari to download
the certificate, install the downloaded profile from **Settings > General >
VPN & Device Management**, and enable full trust under **Settings > General >
About > Certificate Trust Settings**. On Windows, import it into **Trusted Root
Certification Authorities**. On Debian/Linux, add it to the local CA store and
run `sudo update-ca-certificates`. On Android, install it from **Settings >
Security & privacy > More security settings > Encryption & credentials** (menu
names vary by manufacturer). Detailed, platform-specific instructions are in
the [certificate setup and removal guide](docs/certificate-trust.md).

Once the CA is trusted, open `https://cyberdeck.local/` (or the HTTPS URL shown
by the installer) and create the administrator account. Repeat the trust setup
for each device that will use the Hub. If `.local` does not resolve, use the
server IP for the initial HTTP setup; use the hostname printed by the installer
for HTTPS after trusting the CA.

In **Admin**, review the available configuration profiles before applying one.
Use **settings only** to preview subject and site settings without starting
content downloads. A full import can queue acquisitions from its listed
sources. Review the import preview and available storage first.

To add material, use **Admin > Documents** for reference files and **Admin >
Kiwix libraries** for ZIM archives. Keep source, edition, publication date, and
reuse terms with selected content. Hub stores acquired files locally; an
internet source URL alone is not an offline copy.

**Online Source** cards open live websites and are unavailable when the client
or Hub cannot reach the internet. **RSS** cards display recent feed entries
when available; they do not save the linked articles, send push notifications,
or serve as emergency alerts. Treat a cached feed as possibly out of date. For
a step-by-step guide to choosing offline content, see [Survival Cyberdeck Hub
tutorial](docs/content/survival-cyberdeck-hub-tutorial.md).

## Daily use and recovery

- Open a subject card to find related documents and Kiwix libraries. Hub search
  searches catalogue metadata; use the Kiwix search bar to search inside ZIM
  libraries.
- Online Source cards link to live sites; RSS cards read a live feed and may
  show a timestamped cached result. Both need internet access and neither is an
  offline copy or emergency alert service.
- Check available storage in **Admin > System** before acquiring large files.
- Use **Admin > Management > Storage** to adopt an external disk, format it,
  mount an existing ext4 filesystem, or move the library data root. Formatting
  erases the chosen disk; moving data restarts Hub and Kiwix. Keep a verified
  backup and do not unplug a disk while it is in use. A library disk is not a
  backup; use a separate physical disk for recovery copies.
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
CyberChef is a local browser tool for inspecting and transforming data, such as
decoding text, parsing formats, or calculating hashes. Staging requires
internet access and consumes disk space; once staged, it can run locally
without the public CyberChef website. The Hotspot is also an optional host
module. A managed nftables firewall can be enabled in Admin
when its preflight finds no known competing firewall service or input rules. It
is disabled by default. The check cannot find every custom or externally
managed firewall; review the host's firewall and remote-access setup before
enabling it. Read the install guide before changing host network or firewall
settings, especially when administering the host remotely.

Docker is not currently a supported installation path. Use the Debian guide.

## More practical guides

- [Install on Debian or recover a system](docs/runbooks/debian-install.md)
- [Prepare Debian USB installation media](docs/runbooks/bootstrap-install.md)
- [Choose and maintain offline library content](docs/content/survival-cyberdeck-hub-tutorial.md)
- [Review the included profiles](docs/content/starter-profiles.md)
- [Refresh content safely](docs/runbooks/content-refresh.md)
- [Set up or remove device certificate trust](docs/certificate-trust.md)
