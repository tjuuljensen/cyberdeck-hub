# Starter profiles

The Debian install kit includes three optional starter profiles in addition to
the generic Hub starter configuration:

| Profile | Intended use | Language and region |
| --- | --- | --- |
| `danish-crisis-preparedness.json` | Subject structure for locally selected Danish crisis references | Danish; Denmark |
| `generic-off-grid.json` | Subject structure for general off-grid references | English; region-neutral |
| `family-off-grid.json` | Subject structure for a household's own plans and records | English; region-neutral |

These profiles contain subject names, descriptions, and display order only.
They do not include government recommendations, document files, household
contacts, quantities, locations, or download sources. This keeps regional
guidance reviewable and avoids implying that an empty profile is a complete
preparedness plan. Add only sources selected for the household and retain their
publisher, edition, date, and reuse terms in the content record.

To use one, open **Admin > Export and import**, choose **Settings only**, select
the profile, and preview the subject changes before applying them. Applying a
profile can add or edit subject definitions; choose the omitted-subject removal
option only when that is intended. Profiles are available independently of the
current interface language. The profile selector does not yet filter by
language or region.

The installer copies these JSON files into the installed profile directory.
They are imported by the existing settings-only configuration workflow and do
not trigger downloads. The package build and import preview remain required
release checks; no target installation or regional preparedness review is
implied by adding the templates.
