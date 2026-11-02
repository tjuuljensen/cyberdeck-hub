# Profile curation

The [included profiles](starter-profiles.md) are still being curated for 0.2.0.
Use this checklist for the JSON files in `config/debian/profiles/`. A source
being present in a profile does not establish its current availability,
suitability, or permission to redistribute its contents.

## Selection rules

- Match the profile's purpose, language, and region. Label country-specific
  sources clearly when including them in the international-English profile.
- Prefer publisher-issued handouts, checklists, posters, worksheets, and short
  guides for preparedness PDFs. Book-length works and imported local bundles
  need separate review; do not treat them as freely reusable handouts.
- Keep device manuals, games, and other specialist collections in profiles
  intended for those topics instead of adding them to preparedness selections.
- Keep household contacts, credentials, and other private records out of shipped
  profiles. Documents on the Hub are shared with users who can reach it.

## Review each source

1. Record the publisher, source page, direct HTTPS download URL, edition/date,
   language, and applicable region. Use a readable title without a duplicate
   filename or broken transliteration.
2. Check availability, file format, and reuse terms at the publisher. Record
   terms that allow the intended offline use and sharing; an accessible URL
   alone is not permission. Omit unresolved sources from the release profile.
3. Keep a stable `document_id` when updating the URL, filename, or edition of
   the same logical PDF. Use a new identity for a different document or format.
4. Review transfer limits and free-space requirements. Pin a trusted checksum
   where available and verify the acquired file before replacing an old copy.
5. Preview the profile in Admin, inspect Subject mapping and content selections,
   and test both successful acquisition and an unavailable-source retry.
6. Open the selected documents and ZIMs offline from a second client. Record the
   review date and result with the release candidate.

The international-English profile currently includes UK first-aid and knots
references; their country labels must remain visible. The Danish profile's
Denmark map archive is in English. Confirm that these choices still fit the
final profile scope during curation.
