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
- An online full Debian install stages the pinned CyberChef module and leaves
  its service disabled. Admin can enable or disable it; `--skip-cyberchef` and
  `--offline` omit staging.
- Three subject-only starter profiles are included: Danish crisis
  preparedness, generic off-grid preparedness, and a family off-grid pack. They
  contain no government guidance or household data and are not filtered by
  language or region.
- Online source and RSS card definitions are editable in Admin and included in
  configuration import/export. The default online links and Danish police RSS
  feeds appear as separate home cards, alongside subjects and services, and
  disappear when internet connectivity is unavailable. RSS fetching is bounded
  and supports RSS and Atom. It sends no notifications and is not an emergency
  alert channel.
- The supported content update path is manual and administrator-reviewed.
  Scheduled refresh and automatic promotion are not included.

## Supported path and limitations

The candidate installer is source-prepared for existing Debian 13 amd64 and
arm64 systems, but no v0.2.0 physical target has been accepted. Use the Debian
acceptance runbook to close those gates. This does not validate a specific
Raspberry Pi model. Docker remains an experimental preview, not a supported
deployment. Flatnotes and the customizable household preparedness checklist
are deferred.

See the [Debian install and acceptance runbook](../runbooks/debian-install.md)
for install, rollback, backup, restore, offline startup, and second-client gates.
Do not publish the release until dated target evidence is recorded for those
checks, including a disconnected restore rehearsal on a separate destination.
