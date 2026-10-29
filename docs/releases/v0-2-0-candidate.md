# v0.2.0 release candidate

Status: local candidate prepared for review; this is not a published release.
Candidate builds follow the [Hub versioning policy](versioning.md). The tested
`0.2.0` build predates the pre-release labels. `0.2.0-beta.1` adds the first
version label; `0.2.0-beta.2` attempted to reset the Admin page to its first
section, but a late browser scroll restoration still moved it to the previous
position. `0.2.0-beta.3` disables scroll restoration before Admin page parsing
and resets to the top after the page is shown. `0.2.0-beta.4` places Internet
PDF import rows alongside managed Documents, adds per-file retry and cancel,
and keeps a retry-all-failed action. `0.2.0-beta.5` combines Internet PDF
imports with the Documents list, adds visible transfer progress and Remove,
aligns Edit, Download, and Remove controls, and reapplies Admin fragments after
page restoration. `0.2.0-beta.6` moves subjects, services, online sources, and
RSS feeds into one home-card section; adds editable multi-card online-source and
RSS configuration; includes those definitions in configuration import/export;
and labels each card with a translated type and sequence number.
`0.2.0-beta.7` makes online-source and RSS home cards open dedicated detail
pages. The pages show every configured online link and the complete bounded set
of fetched RSS items, and disappear when internet access is unavailable.
`0.2.0-beta.8` adds separate search terms for documents, token-based matching,
and relevance ordering. Hub search remains a metadata catalogue search; use the
Kiwix search bar to look inside installed ZIM libraries.
`0.2.0-beta.9` displays RSS publication dates in the Cyberdeck's configured
timezone and the selected interface language. Feed timestamps are normalized to
UTC; entries with missing or invalid dates show a translated fallback.
`0.2.0-beta.10` accepts common RSS and Atom item date fields and timestamp
formats, tries alternate date fields when one is malformed, assumes UTC for
timezone-less values, and falls back to UTC display if a client cannot format
the configured timezone.
`0.2.0-beta.11` makes each RSS headline link to its article and aligns the
publication time on the right side of the same header row.
`0.2.0-beta.12` records each card's original language, lets administrators edit
the active language and one selected translation while preserving other
translations, and includes the language metadata in configuration imports and
exports. `0.2.0-beta.13` migrates configurable card and child-entry text out of
the UI locale catalogues into saved configuration, preserves legacy mappings
for upgrades and imports, skips user content in translation-ID mode, and removes
obsolete card copy from the locale files.
`0.2.0-beta.14` moves CyberChef runtime guidance into the README, reads its
status without sudo, and uses a checkbox for its module state like Hotspot.
`0.2.0-beta.15` keeps storage and disk information visible while folding
storage actions, and folds system details under the current server name.
`0.2.0-beta.16` keeps network and local storage visible outside the System
Overview fold and reads CyberChef status without relying on a helper version.
`0.2.0-beta.17` makes empty-card visibility configurable for document, Online
Source, and RSS cards, and replaces the timezone text field with a region-grouped
picker.
`0.2.0-beta.18` gives Online Source and RSS home cards a primary-text gradient
that fades from left to right, matching the service-card treatment.
`0.2.0-beta.19` changes Online Source and RSS card borders to the muted document
card border color.
`0.2.0-beta.20` adds a guided Debian USB bootstrap, Danish and international
English curated profiles, an optional managed firewall module, and the
relational Card storage migration. It removes the unsupported Docker preview
and documents the split between Hub bootstrap and the parent's Windows
developer deployment helper.
`0.2.0-beta.24` starts new cyberdecks without preloaded RSS or Online Source
examples, adds per-card transfer and origin-source metadata, and adds card
deletion and a content reset that preserves administrator access and server
settings. It also adds a hideable Start card with a local getting-started guide.
`0.2.0-beta.25` replaces card and content removal popups with inline
two-click confirmation and clarifies when container runtime mode cannot manage
the host firewall. It also advances the static asset cache version.
`0.2.0-beta.26` keeps card deletion controls visually neutral while armed and
labels populated cards with their connected content count.
`0.2.0-beta.27` hides unidentified, unmounted, partitionless devices from the
storage overview while retaining the full disk inventory for backend safety
checks.
`0.2.0-beta.28` removes the redundant success popup after saving Hotspot
settings.
`0.2.0-beta.29` applies the configured site accent color to the getting-started
page.
`0.2.0-beta.30` combines populated-card type and content count on one metadata
line.
`0.2.0-beta.31` adds a red, three-step confirmation before deleting a card
with contents.
`0.2.0-beta.32` gives delete buttons the same filled warning-red style across
content management.
`0.2.0-beta.33` resets an incomplete delete confirmation after eight seconds
of inactivity at each confirmation step.
`0.2.0-beta.34` aligns RSS and Online Source entry management, adds enabled
controls for both types, groups the Show all views by card, and restores safe
disk Adopt and Unmount actions to each disk card.
`0.2.0-beta.35` adds spacing between Library folder configuration and the
Refresh disks button.
`0.2.0-beta.36` standardizes entry-list actions, five-second confirmations,
select and menu chevrons, and connected card groups.
`0.2.0-beta.37` opens ZIM and document selection groups in import previews and
opens the document and content groups in export options for easier discovery.
`0.2.0-beta.38` accepts standalone ZIM and PDF files in Admin import, previewing
them as local libraries or documents. Exported JSON and ZIP imports preserve
online source URLs and any selected cached PDF copies.
`0.2.0-beta.39` makes the import picker show all files so ZIMs remain visible in
file dialogs that do not recognize their MIME type, and labels duplicate notices
with the import category for context.
`0.2.0-beta.40` adds item counts to matching import and export categories and
shows the selected ZIM count in the import storage summary.
`0.2.0-beta.41` classifies cached public document files under Documents during
import, lets administrators choose those copies, and preserves their source URLs.
`0.2.0-beta.42` puts ZIM choices at the top of import review, aligns online
document imports with the export category, and adds one checkbox for cached
PDF copies. A bundled cached copy and its matching online URL no longer produce
a duplicate warning.
`0.2.0-beta.43` places the Documents section alongside ZIM choices, before
subject mappings, so it remains visible near the top of the import review.
`0.2.0-beta.44` discovers cached online PDFs from their bundled catalogue
metadata as well as top-level config assets, and suppresses duplicate-content
notices for those paired cache/source entries.
`0.2.0-beta.45` keeps cached-copy selection available when files are already
installed, labels those entries as duplicates, and reuses identical installed
files instead of blocking the import with destination conflicts.
`0.2.0-beta.46` orders import categories to match export, and folds Card mapping
into a collapsed accent-coloured submenu.
`0.2.0-beta.47` puts Card mapping first with live create/existing counts, colors
the mapping choices by action, splits Site settings into hierarchical Display
Settings and Customization checkboxes, and removes the import-mode selector.
`0.2.0-beta.48` adds stable identities for online PDFs, refreshes an installed
copy in place after validating its replacement, and collapses byte-identical
online PDF downloads while retaining their source identities.
`0.2.0-beta.49` removes the legacy omitted-subject deletion checkbox from the
Admin import form.

## Included scope

- Local catalogue search matches all query words across titles, filenames,
  subjects, short overviews, and optional search terms. Title matches rank
  highest. It does not index PDF or ZIM full text; Kiwix search can search ZIM
  titles and, for supported archives, full text.
- Internet PDF imports show per-file progress and failure state in Admin, with
  retry for failed downloads. Configuration exports preserve online source
  links and metadata, not remote PDF payloads. The optional, manually started
  Debian recovery backup copies the entire configured data root, including
  acquired PDFs, their records, and other acquired content, then verifies the
  copy. There is no PDF-only backup option or scheduled backup in v0.2.0.
- An online full Debian install installs the pinned CyberChef module and leaves
  its service disabled. Admin can enable or disable it; later updates preserve
  that state. `--offline` omits installation because it cannot download the
  pinned archive.
- Three subject-only starter profiles are included: Danish crisis
  preparedness, generic off-grid preparedness, and a family off-grid pack. They
  contain no government guidance or household data and are not filtered by
  language or region.
- Two curated profiles are included from the supplied emergency library:
  a Danish/Denmark profile and an international-English profile. The source
  curation rule and omissions are recorded in `docs/content/profile-curation.md`.
- The Hub repository owns the guided Debian USB bootstrap as well as the direct
  existing-Debian installer. The sibling `cyberdeck` repository retains its
  Windows developer deployment helper and target evidence.
- Online source and RSS card definitions are editable in Admin and included in
  configuration import/export. The default online links and Danish police RSS
  feeds appear as separate home cards, alongside subjects and services, and
  disappear when internet connectivity is unavailable. RSS fetching is bounded
  and supports RSS and Atom. It sends no notifications and is not an emergency
  alert channel.
- The supported content update path is manual and administrator-reviewed.
  Scheduled refresh and automatic promotion are not included.

## Supported path and limitations

The source installer targets existing Debian 13 amd64 and arm64 systems. The
guided custom USB flow currently prepares Debian 13 amd64 media. No v0.2.0
physical target has been accepted; use the Debian acceptance runbook to close
those gates. Generic ARM64 support does not validate a particular Raspberry Pi
model. Docker artifacts have been removed until a container path can pass
startup, persistence, backup/restore, restart, upgrade, and optional-module
acceptance. Flatnotes and the customizable household preparedness checklist
remain deferred.

See the [Debian install and acceptance runbook](../runbooks/debian-install.md)
for install, rollback, backup, restore, offline startup, and second-client gates.
Do not publish the release until dated target evidence is recorded for those
checks, including a disconnected restore rehearsal on a separate destination.
