# Hub versioning

Cyberdeck Hub uses semantic versions in `MAJOR.MINOR.PATCH` form. Until the
first stable public release, versions use a SemVer pre-release suffix:

- `alpha.N` while features or scope are still changing.
- `beta.N` once the planned release scope is in place and candidates are being
  exercised by users.
- `rc.N` after scope is frozen and only release-blocking fixes are accepted.
- The final release drops the suffix, for example `0.2.0`.

Use the format `0.2.0-beta.1`, `0.2.0-beta.2`, `0.2.0-rc.1`, then `0.2.0`.
Do not use dotted forms such as `0.2.0.preview.1`; SemVer pre-release labels
follow a hyphen. `APP_VERSION` is the version shown in the Hub UI and used for
static-asset cache busting. The source-kit builder and deployment launcher
should report the same app version and identify its source commit.

Give every changed candidate a new version. Do not rebuild different contents
under an existing candidate version. For each candidate, record its version,
clean source commit, source-kit SHA-256, source checks, and dated target results
in the release tracking record. Use an annotated Git tag such as
`v0.2.0-beta.1` only after repository and release metadata are ready for review;
do not configure or publish a remote as part of local candidate testing.

The first candidate deployed as `0.2.0` predates this convention. The next
candidate starts at `0.2.0-beta.1`; later beta or release-candidate builds
increment their numeric suffix.
