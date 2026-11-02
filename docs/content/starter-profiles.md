# Starter profiles

Cyberdeck Hub installs an empty generic starter configuration and optional
profiles. The curated profiles are still being reviewed for 0.2.0. Use
**Admin > Import**, select a profile, and preview it before applying. Review
**Card mapping**, site settings, and the selected Documents and Kiwix libraries.
To add only a subject structure, use one of the subject-only templates below.
For a curated profile, clear the content selections if you do not want downloads.
Applying selected sources can queue files and ZIM libraries; check available
storage first.

## Curated profiles

| File | Display name | Primary target | Contents |
| --- | --- | --- | --- |
| `kriseberedskab-da-dk.json` | Kriseberedskab i Danmark | Danish; Denmark | Danish preparedness and first-aid subjects, selected direct-download PDFs, Denmark maps, and Danish Wikipedia. |
| `international-emergency-preparedness-en-int.json` | Emergency Preparedness (International English) | English; international | Practical-skills and first-aid subjects, English direct-download PDFs, and selected English Kiwix libraries. Country-specific sources are identified in their titles and descriptions. |

The filename convention is `<purpose>-<language>-<region>.json`: use lowercase language and region codes, such as `da-dk` for Danish in Denmark or `en-int` for international English. The country code is ISO 3166-1 alpha-2; `int` denotes an international target. Lowercase filenames are required by the installer and profile selector. The profile `name` is the user-facing display name. Keep content selections aligned with the target; do not put device-specific manuals into regional preparedness profiles.

The curated PDFs are intended as standalone handouts, checklists, posters, worksheets, or short guidance documents published for direct download. Book-length PDFs and local archive imports are not treated as downloadable handouts. Follow the [profile curation checklist](profile-curation.md) when reviewing each source. Inclusion is not a separate license grant; retain publisher, edition, date, and reuse terms when maintaining a profile.

## Subject-only templates

These templates remain available for households that want to build their own library structure without preselected source links:

| File | Intended use | Language and region |
| --- | --- | --- |
| `danish-crisis-preparedness.json` | Subject structure for locally selected Danish crisis references | Danish; Denmark |
| `generic-off-grid.json` | Subject structure for general off-grid references | English; region-neutral |
| `family-off-grid.json` | Subject structure for a household's own plans and records | English; region-neutral |

They contain subject names, descriptions, and display order only. They do not include government recommendations, document files, household contacts, quantities, locations, or download sources. The profile selector does not filter by language or region.
