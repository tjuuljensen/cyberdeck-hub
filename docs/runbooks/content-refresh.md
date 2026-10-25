# Content refresh

This is a manual, administrator-reviewed refresh path for Hub content. The
Hub does not schedule unattended Wikipedia, map, or PDF updates. A new edition
is downloaded under a new filename, checked against its manifest, then
introduced through the normal Hub import flow. The old edition remains in
place until the new one is verified and a backup is available.

## Before acquisition

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

## Acquire and verify

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

## Promote and recover

1. Import the reviewed manifest or configuration through Admin. Preview the
   subject mapping, paths, conflicts, storage reserve, and selected Internet
   PDFs before applying it.
2. Confirm the new document opens and that its reader/search path works on the
   intended Hub. Raw map datasets are not useful offline unless a compatible
   viewer and its required assets are also installed and tested.
3. Make and verify a recovery backup on a separate physical disk. The recovery
   backup includes acquired PDF and ZIM files; configuration exports keep
   online source links and do not include remote payloads.
4. Keep the prior version until a second-client offline check and a restore
   rehearsal have passed. Remove superseded files only through a reviewed
   retention procedure.

For frequent Wikipedia and map refreshes, this manual process is the supported
v0.2.0 path. Automated scheduling, automatic promotion, and automatic cleanup
remain unsupported until staged updates, rollback, resource limits, and
low-resource target behavior have been accepted.
