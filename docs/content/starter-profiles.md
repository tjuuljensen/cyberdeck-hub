# Starter profiles

Cyberdeck Hub installs an empty generic starter configuration and optional
profiles. Use **Admin > Import**, choose **Settings only**, and preview before
applying a profile. This mode changes subject definitions without starting
content downloads. Applying a full curated profile can queue its listed source
files and ZIM libraries; review the sources and available storage first.

## Curated profiles

| File | Display name | Primary target | Contents |
| --- | --- | --- | --- |
| `crisis-preparedness-da-DK.json` | Kriseberedskab i Danmark | Danish; Denmark | Danish preparedness and first-aid subjects, selected direct-download PDFs, Denmark maps, and Danish Wikipedia. |
| `emergency-preparedness-en-INT.json` | Emergency Preparedness (International English) | English; international | Practical-skills and first-aid subjects, English direct-download PDFs, and selected English Kiwix libraries. Country-specific sources are identified in their titles and descriptions. |

The filename convention is `<purpose>-<language>-<region>.json`: use a language code and an ISO 3166-1 alpha-2 country code for country-specific profiles, or `INT` for an international target. The profile `name` is the user-facing display name. Keep content selections aligned with the target; do not put device-specific manuals into regional preparedness profiles.

The curated PDFs are intended as standalone handouts, checklists, posters, worksheets, or short guidance documents published for direct download. Book-length PDFs and local archive imports are not treated as downloadable handouts. See the [curation and exclusion record](profile-curation.md) for each excluded item and its reason. The record is a source-selection note, not a separate license grant; retain publisher, edition, date, and reuse terms when maintaining a profile.

## Subject-only templates

These templates remain available for households that want to build their own library structure without preselected source links:

| File | Intended use | Language and region |
| --- | --- | --- |
| `danish-crisis-preparedness.json` | Subject structure for locally selected Danish crisis references | Danish; Denmark |
| `generic-off-grid.json` | Subject structure for general off-grid references | English; region-neutral |
| `family-off-grid.json` | Subject structure for a household's own plans and records | English; region-neutral |

They contain subject names, descriptions, and display order only. They do not include government recommendations, document files, household contacts, quantities, locations, or download sources. The profile selector does not filter by language or region.
