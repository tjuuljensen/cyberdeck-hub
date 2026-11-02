# TODO

## Before 0.2.0

- [ ] Finish curating the included profiles: titles, language/region, source URLs,
  editions, reuse terms, download sizes, and import behavior.
- [ ] Clarify the Docker Admin **Modules** wording: services run in separate
  containers. Consider links to separately configured tools such as CyberChef
  or FlatNotes when they are part of the same stack.
- [ ] Complete and document recovery-package preparation, and make the recovery
  backup usable from the shipped source kit. The current backup requires a
  package-cache marker and source directories absent from the kit.
- [x] Bundle `docs/` and `TODO.md` in the Debian kit so its documentation links
  resolve offline after extraction.
- [ ] Record install, upgrade, rollback, offline-client, and backup/restore
  acceptance for the final candidate and each advertised deployment path.
- [x] Clarify that repository files are MIT-licensed, except where separate
  license terms are stated; external third-party material retains its own terms.
- [ ] Assign the final version, build from a clean commit, and record checksums
  and release evidence before tagging.

See the [release readiness record](docs/releases/v0-2-0-candidate.md) for scope,
evidence, and acceptance criteria. Longer-term schema and module work is tracked
in the [architecture review](docs/architecture-review.md).
