# v0.2.0 release candidate

Status: local candidate prepared for review; this is not a published release.
Candidate builds follow the [Hub versioning policy](versioning.md). The tested
`0.2.0` build predates the pre-release labels; the next candidate is
`0.2.0-beta.1`.

## Included scope

- Local catalogue search covers stored titles, descriptions, filenames, and
  subject metadata. It does not index PDF or ZIM full text.
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
- Online crisis links and an on-demand reader for official Danish police RSS
  updates appear only when connectivity is available. The reader sends no
  notifications and is not an emergency alert channel.
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
