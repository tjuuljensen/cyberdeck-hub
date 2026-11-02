# 0.2.0 release readiness

Reviewed: 2026-11-02. **Status: in preparation; not ready for the final 0.2.0
release.** The source currently reports `0.2.0-beta.54`. Profile curation is
still in progress, and recovery and target acceptance remain open.

The repository can be shared for development review with these limitations
visible. Publishing the final release requires the evidence below. This record
summarizes current scope; superseded beta UI changes remain in Git history.
Follow the [versioning policy](versioning.md) when preparing a new candidate.

## Included scope

- A local catalogue of Documents (PDF, DOCX, and packaged HTML) and Kiwix ZIM
  libraries. Catalogue search covers metadata; Kiwix provides search within ZIMs.
- Subject, Online Source, and RSS cards with editable content and translations.
  New installations start without preloaded Online Source or RSS cards.
- Import previews with content selection and Subject mapping; exports with
  metadata, source links, and optional selected local files or cached PDF copies.
- Stable online-PDF identities and verified replacement of downloaded copies.
- An empty starter configuration, three subject-only templates, and two curated
  preparedness profiles. The profiles are draft selections pending review.
- Debian 13 installation on amd64/arm64, guided Debian amd64 USB preparation,
  and a Windows deployment launcher, all maintained in this repository.
- Optional Debian CyberChef, hotspot, firewall, and storage controls. Online
  setup stages CyberChef; its service and the managed firewall start disabled.
- A Docker Compose stack with Hub, Kiwix, Caddy, and a public-CA exporter.
  Container mode does not expose Debian host controls or install extra addons.
- Manual content refresh. Scheduled acquisitions and automatic promotion are
  outside the 0.2.0 scope.

## Remaining release gates

| Gate | Evidence required before release |
| --- | --- |
| Profile curation | Review titles, language/region, editions, source and download URLs, reuse terms, checksums where available, and storage bounds. Exercise every included profile's preview, selected downloads, failures, and retries. See the [curation checklist](../content/profile-curation.md). |
| Recovery workflow | Provide and document verified package-cache preparation. `app/library.py backup` requires `recovery-packages/COMPLETE`, which no script in this repository creates. Its source-copy list also requires `tests/`, absent from the shipped kit. Resolve both gaps and complete a disconnected restore on a separate destination. |
| Debian lifecycle | Record install, upgrade, rollback, reboot, offline access from a second client, backup/restore, and resource results for the final candidate. Follow the [Debian acceptance record](../runbooks/debian-install.md#release-acceptance-record), including its amd64 and arm64 target requirements. |
| Guided USB bootstrap | Record media boot, Debian installation, first-boot setup, and retry behavior on the advertised target. Building an ISO or overlay alone does not close this gate. |
| Docker lifecycle | Record startup, CA trust, persistent documents and ZIMs, restart/recreate, upgrade, and restoration of all named volumes. Resolve the Admin Modules wording in [TODO](../../TODO.md). |
| Release identity | Assign a new candidate version after changes; build from a clean commit and record its version, commit, kit SHA-256, test results, and dated target evidence. Use the final `0.2.0` version and tag only after acceptance. |

Architecture extraction and a schema-version ledger are follow-up work, not
requirements for a broad rewrite before 0.2.0. Existing-install migration and
rollback checks are required: startup still migrates older Subject records to
shared Card tables and retains a `library_subject` compatibility view. See the
[architecture review](../architecture-review.md).

## Evidence on record

### License scope clarified, 2026-11-02

The [MIT License](../../LICENSE) covers repository files, including documentation,
profiles, manifests, and deployment files, unless separate license terms are
stated. External third-party material linked to, referenced by, or downloaded
through the project remains subject to its own terms. This resolves the
repository license-scope item; reviewing external sources remains part of
profile curation.

### Documentation review, 2026-11-02

Windows-native checks of the documentation working tree passed: 51 local links
and anchors across 14 Markdown files, JSON parsing for all five profiles, LF
line endings, and `git diff --check`. The original source-kit validator accepted 71
source files and its helper, sudoers, and firewall contracts. Source inspection
confirmed the recovery gap listed above and missing guides in the original kit.
These checks do not validate profile downloads, full application behavior,
Docker runtime, or physical-target acceptance.

### Kit documentation completed, 2026-11-02

The Debian kit now includes all of `docs/` and `TODO.md` alongside README and
LICENSE. A Windows-native build and extraction produced 85 files without
duplicate archive entries; all 51 local documentation links and anchors resolved
inside the extracted kit. All seven existing kit-builder tests passed, including
deterministic builds and source validation. The separate recovery workflow gap
remains open.

### Historical deployment evidence

The historical result below is retained because it verifies the migration to
complete Hub-owned deployment and the repair of helper/firewall permissions.
It applies to beta.50, not to all later changes or the final release. The parent
launcher mentioned here is historical provenance; current deployment uses this
repository's launcher.

### beta.50 targeted RPi upgrade verification, 2026-10-30

- Deployed Hub source commit `b78cdd3f2f423b3fa66b4a1a99a8a4f76e315634`,
  version `0.2.0-beta.50`, through the parent compatibility launcher at commit
  `e0d66e973fad9b27c3920404916780b86bbd61d4` from clean checkouts.
- The complete 72-file kit SHA-256 was
  `e7dfd595de054d2b5414cf56f514526965dab572b19b946b411aca6165010cfa`.
  The target verified the transferred checksum and source contract before apply.
- Workstation validation: 39 focused tests passed across kit construction,
  stale-component rejection, parent delegation, runtime verification, snapshots,
  host helpers, and installer previews. PowerShell parsing, Bash syntax, and
  focused Git whitespace checks passed.
- Target: existing Debian 13.7 aarch64 RPi installation. Apply preserved
  `/srv/cyberdeck`, created recovery snapshot
  `da252d56e4af406cb1f94e4e1f2e0b0b`, and refreshed the complete runtime.
  Backup: `/var/backups/cyberdeck/deployments/da252d56e4af406cb1f94e4e1f2e0b0b`.
- The installed admin helper SHA-256 matched the Hub source:
  `899c0cbcc8bc706870754590c07c30911041dda56e2d63585f06e94b2474cdf6`.
  `visudo` accepted the installed policy. Firewall status and change
  authorization passed as the service account inside the running web mount
  namespace. The already-enabled module's actual `firewall-enable` operation
  also succeeded in that namespace.
- The refreshed firewall unit restarted successfully and remained enabled.
  Status reported available, enabled, active, and no conflicts. The loaded
  nftables input chain had policy drop, allowed SSH port 22 and Hub ports 80,
  443, and 8445, and retained DNS, DHCP, mDNS, loopback, ICMP, and established
  connection rules. Hub and Kiwix were active.
- Hub HTTPS returned success using the installed CA on the Pi. An independent
  workstation Python TLS request verified that CA and the server hostname and
  received HTTP 200. Windows curl's Schannel stack could not determine local-CA
  revocation status, so it was not used as the external TLS acceptance result.
- These are targeted upgrade and firewall checks, not reboot, offline-library,
  or backup/restore acceptance. The recovery snapshot contains the incompatible
  pre-repair helper and policy; inspect it before considering rollback.
  To preview that snapshot, use the Hub Windows launcher with the intended
  `-Target`, `-ExpectedHost cyberdeck-pi`, and
  `-RollbackId da252d56e4af406cb1f94e4e1f2e0b0b`. Only
  `-ExecuteRollback` performs restoration; see the Debian runbook.
