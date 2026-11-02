# Cyberdeck Hub

Cyberdeck Hub is a local-first reference library for households, community
groups, workshops, and other small teams that want useful information available
on a local network even when internet access is unavailable. It brings selected
PDFs and offline Kiwix libraries together in a searchable catalogue, with an
administrator area for managing content and the host.

**Release status:** 0.2.0 is in preparation. The application currently identifies
as `0.2.0-beta.54`; the included profiles are still being curated. See the
[release readiness record](docs/releases/v0-2-0-candidate.md) for outstanding
validation and the [TODO list](TODO.md) for remaining work.

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
| You want to run the Hub in containers | Use the [Docker Compose guide](docs/runbooks/docker-compose.md) for a Hub, Kiwix, and Caddy stack. |
| You are developing or deploying a Hub change | Build a source-only Debian kit from this checkout with `python3 scripts/debian/build-kit.py --output ./cyberdeck-hub-debian-kit.tar.gz`, then follow the [manual Debian install guide](docs/runbooks/debian-install.md) to preview and install it on the target. |

The install guide identifies supported Debian versions and architectures and
separates source/package checks from physical-target acceptance. Hub deployment
has succeeded on a Raspberry Pi 4 running 64-bit Debian 13; this does not
establish support for every Pi model or accessory.

### Install on a Raspberry Pi 4

Use Raspberry Pi Imager to prepare a microSD card with the current **Raspberry
Pi OS Lite (64-bit)** image. In Imager's OS customisation settings, configure:

- Hostname: `cyberdeck-pi` (choose a unique name if you have more than one Hub)
- Username: `operator` (`cyberdeck` is reserved for the Hub service account)
- Your Wi-Fi country and, if using Wi-Fi for setup, network credentials
- SSH with public-key authentication

Raspberry Pi's [headless setup guide](https://www.raspberrypi.com/documentation/computers/getting-started.html)
covers Imager customisation. Insert the card, boot the Pi, and connect over SSH:

```sh
ssh operator@cyberdeck-pi.local
```

If `.local` name resolution is unavailable, use the Pi's address instead:
`ssh operator@<PI-IP>`. Confirm that the image is 64-bit Debian 13-based before
installing:

```sh
cat /etc/os-release
dpkg --print-architecture
```

The architecture should be `arm64`. Update the OS, then reboot if requested:

```sh
sudo apt update
sudo apt full-upgrade
sudo reboot
```

Build a source kit from the intended Cyberdeck Hub checkout on a connected
workstation, then transfer the kit and checksum to the Pi. For example, on a
Linux, macOS, or Git Bash workstation:

```sh
python3 scripts/debian/build-kit.py --output ./cyberdeck-hub-debian-kit.tar.gz
sha256sum cyberdeck-hub-debian-kit.tar.gz > cyberdeck-hub-debian-kit.tar.gz.sha256
scp cyberdeck-hub-debian-kit.tar.gz cyberdeck-hub-debian-kit.tar.gz.sha256 \
  operator@cyberdeck-pi.local:~
```

Then, on the Pi, verify and unpack the kit, preview the installer, and apply it:

```sh
set -e
sha256sum -c cyberdeck-hub-debian-kit.tar.gz.sha256
mkdir -p cyberdeck-hub-source
tar -xzf cyberdeck-hub-debian-kit.tar.gz -C cyberdeck-hub-source
cd cyberdeck-hub-source
bash scripts/debian/install.sh --hostname cyberdeck-pi
sudo bash scripts/debian/install.sh --apply --hostname cyberdeck-pi
```

The preview must complete successfully before applying. The installer keeps
Raspberry Pi OS in place; it does not repartition the card or change the Pi's
hostname or network configuration. For kit checksums, recovery, and detailed
post-install checks, follow the [manual Debian install
guide](docs/runbooks/debian-install.md). After installation, check Wi-Fi
readiness with:

```sh
sudo cyberdeck-wifi-diagnostics
```

The diagnostic reports radio state, detected interfaces, AP-mode support, and
firmware errors. Resolve any reported radio or driver issue for the specific
adapter before testing the optional hotspot.

## First use

After installation, connect your phone or computer to the same local network
as the Hub. On Debian, start certificate setup at `http://cyberdeck.local/` (or
use the server IP printed by the installer; the standard Cyberdeck hotspot is
`http://10.42.0.1/`). With Docker Compose, open
`http://<CYBERDECK_HOSTNAME>/help/certificate` as described in the
[Compose guide](docs/runbooks/docker-compose.md). HTTP is only for setting up
certificate trust; do not enter passwords or use the Hub over HTTP. Download
the CA certificate, verify its SHA-256 fingerprint against the value on the
server, then install it as a trusted root certificate on the device. On
iPhone, use Safari to download
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
A full import can queue acquisitions from its listed sources. Review the import
preview and available storage first. Online PDF profiles use a stable
`document_id` for each logical document. Keep that ID when its URL, filename, or
edition is updated; use a different ID for a genuinely different document or
format. The Hub verifies a refreshed PDF before replacing its installed copy.

To add material, use **Admin > Documents** for reference files and **Admin >
Kiwix libraries** for ZIM archives. Keep source, edition, publication date, and
reuse terms with selected content. Hub stores acquired files locally; an
internet source URL alone is not an offline copy.

### Document uploads

Administrators can add these attachment types under **Admin > Documents**:

- **PDF** (`.pdf`)
- **Microsoft Word** (`.docx`)
- **HTML publication** (`.zip`), which must contain a top-level `index.html` or
  `index.htm`. This is for a packaged website, not a general-purpose ZIP file.

Each attachment can be up to 2 GiB. An HTML ZIP can contain up to 2,500 files
and expand to at most 512 MiB. You can upload multiple attachments, download
one attachment from a public HTTPS URL, or combine an upload with a URL. An
optional cover image can be JPEG, PNG, or WebP. Other document formats such as
legacy `.doc`, EPUB, and plain text are not accepted as attachments. Add ZIM
archives separately under **Admin > Kiwix libraries**.

For documents added from a URL, use **Edit** to correct the **Download URL**
(and each attachment URL when applicable), then **Save changes**. This does not
start a download. Reopen **Edit** and select **Update downloaded copy** to fetch
and validate a replacement; the current copy remains available if the update
fails. Document identifiers, titles, and other metadata are preserved.

Optional **Origin Source** and search terms are under **Metadata**. Origin Source
is the publisher or reference page, separate from the file download URL.
**File details** shows available filenames, sizes, and stored checksums.
When adding a ZIM, **Download verification** accepts an optional SHA-256.
Automatic publisher-checksum lookup remains enabled; conflicting checksums are
rejected, and a supplied checksum can be used when no publisher checksum is available.

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
- Export configuration for metadata and source links. Export can also package
  selected local documents and cached PDF copies; check the export selections.
  This is not a complete system backup. Review the [backup and restore
  limitations](docs/runbooks/debian-install.md#backup-and-restore) and rehearse
  recovery before relying on a backup.
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

CyberChef is installed during online Debian setup from a pinned release, while
its service stays disabled until an administrator enables it in Admin. Setup
preserves the current CyberChef service state on later updates.
CyberChef is a local browser tool for inspecting and transforming data, such as
decoding text, parsing formats, or calculating hashes. Installation requires
internet access and consumes disk space; once staged, it can run locally
without the public CyberChef website. The Hotspot is also an optional host
module. A managed nftables firewall can be enabled in Admin
when its preflight finds no known competing firewall service or input rules. It
is disabled by default. The check cannot find every custom or externally
managed firewall; review the host's firewall and remote-access setup before
enabling it. Read the install guide before changing host network or firewall
settings, especially when administering the host remotely.

For the container deployment, see the [Docker Compose guide](docs/runbooks/docker-compose.md).
It runs the Hub and Kiwix in separate containers behind Caddy. Host controls such
as hotspot, firewall, power, hostname, and storage management are unavailable in
container mode. For a host-integrated installation, use the Debian guide.

## More practical guides

- [Install on Debian or recover a system](docs/runbooks/debian-install.md)
- [Prepare Debian USB installation media](docs/runbooks/bootstrap-install.md)
- [Choose and maintain offline library content](docs/content/survival-cyberdeck-hub-tutorial.md)
- [Review the included profiles](docs/content/starter-profiles.md)
- [Refresh content safely](docs/runbooks/content-refresh.md)
- [Set up or remove device certificate trust](docs/certificate-trust.md)
- [Configure Online Source and RSS cards](docs/content/online-crisis-links.md)
- [Review architecture and migration work](docs/architecture-review.md)
- [Track 0.2.0 release readiness](docs/releases/v0-2-0-candidate.md)

## License

Repository files are licensed under the [MIT License](LICENSE), including code,
documentation, configuration, profiles, and deployment files, unless a file
explicitly carries separate license terms. External third-party material linked
to, referenced by, or downloaded through the project remains subject to its own
licenses and terms. A link in a profile or guide does not make its destination
content MIT-licensed.
