# Content refresh

Content refresh is manual and administrator-reviewed. The Hub does not schedule
unattended Wikipedia, map, or PDF updates. Keep a backup before replacing content.

## Refresh a document in Admin

For a document added from a URL, open **Admin > Documents > Edit**, correct the
Download URL or attachment URLs if necessary, and save. Saving metadata does
not download a replacement. Reopen **Edit** and select **Update downloaded copy**
to fetch and validate it. The current copy remains available if the update fails.

For profile-based online PDFs, retain the same `document_id` when revising the
source URL, destination filename, or edition of the same logical document.
Preview the updated profile before applying it. A different document or format
needs a different identity. See the [profile curation checklist](../content/profile-curation.md).

## Refresh through an acquisition manifest

The lower-level `app/library.py` workflow treats acquired paths as immutable.
Download a new edition under a new filename, verify it, then introduce it through
Admin import. Keep the old edition until the replacement and backup are verified.

### Before acquisition

1. Review the upstream publisher/catalogue, edition date, format, and reuse
   terms. Record the source page and the direct HTTPS download URL.
2. Create a new manifest version and use a new flat destination filename, such
   as `public/wikipedia-en-2026-10.zim` or `public/map-region-2026-10.pdf`.
   Do not edit the source or hash for an already acquired path; the acquisition
   lock treats that path as immutable.
3. Set a deliberate `max_bytes` limit. Add a trusted publisher checksum when
   one is available. Without it, the Hub records a local hash that detects
   later changes but does not prove who published the original bytes.
4. Confirm available disk space and keep the current library intact.

### Acquire and verify

Run from the source kit on the Debian Hub. Replace the paths with the actual
manifest and configured data root:

```sh
python3 app/library.py plan --manifest /path/to/reviewed-edition.json
sudo python3 app/library.py fetch --root /srv/cyberdeck --manifest /path/to/reviewed-edition.json
sudo python3 app/library.py verify --root /srv/cyberdeck --manifest /path/to/reviewed-edition.json
sudo python3 app/library.py verify --root /srv/cyberdeck
```

`plan` prints the declared transfer and storage bounds without downloading.
`fetch` writes to a partial file, verifies an optional pinned SHA-256, then
promotes the complete file and records its hash. Failed resumable downloads can
be retried with the same manifest. If an edition changes, use a new filename
and manifest entry rather than replacing the existing acquired path.

The first verified acquisition creates a local hash when the manifest has no
trusted expected hash. Review the downloaded file itself and record its edition
and source review; a successful transfer is not content or rights validation.

### Promote and recover

1. Import the reviewed manifest or configuration through Admin. Preview the
   subject mapping, paths, conflicts, storage reserve, and selected Internet
   PDFs before applying it.
2. Confirm the new document opens and that its reader/search path works on the
   intended Hub. Raw map datasets are not useful offline unless a compatible
   viewer and its required assets are also installed and tested.
3. Make and verify a backup on a separate physical disk. Configuration exports
   preserve source links and can include selected local files and cached PDFs;
   they are not a complete system backup. The Debian recovery command is intended
   to include the data root, but its [current prerequisites and kit limitations](debian-install.md#backup-and-restore)
   must be resolved before relying on that workflow.
4. Keep the prior version until a second-client offline check and a restore
   rehearsal have passed. Remove superseded files only through a reviewed
   retention procedure.

For frequent Wikipedia and map refreshes, this manual process is the supported
v0.2.0 path. Automated scheduling, automatic promotion, and automatic cleanup
remain unsupported until staged updates, rollback, resource limits, and
low-resource target behavior have been accepted.
