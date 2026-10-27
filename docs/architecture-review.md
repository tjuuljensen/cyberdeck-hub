# Cyberdeck Hub architecture review

Reviewed: 2026-10-27. This is a source-level review of the v0.2.0 candidate. It does not claim physical-target or production-load validation.

## Current architecture

The application is a single Flask module (`app/webapp.py`, about 6,200 lines) that combines HTTP routes, validation, localization, SQL queries and migrations, file handling, import/export orchestration, network fetchers, background work, and host-control adapters. `app/library.py` separately owns download, archive, and recovery operations. Templates and browser scripts are split by page/function, but several Admin and API concerns are implemented in the large Flask module.

SQLite stores administrator credentials, documents and attachments, ZIM records, cards and child entries, site settings, and import transaction markers. The v0.2.0 candidate moves Subject, Online Source, and RSS records into the shared relational card model at startup, with a compatibility view for existing subject queries. Portable configuration and acquisition/recovery state still use JSON files. Binary documents and ZIMs are stored on disk, separate from metadata. Other schema evolution still uses conditional startup DDL rather than a complete migration ledger.

This design has useful local-first properties: no external database service is needed, foreign keys are enabled, data and private state have clear roots, imports journal filesystem changes for recovery, and privileged host operations go through a root-owned allowlist helper. The install kit is deterministic and validates included sources. These are principles to retain.

## Maintenance risks

- Route handlers, data access, platform controls, and long-running workflows share one module, making changes difficult to isolate and review.
- A startup migration and compatibility view now bridge older `library_subject` databases to the unified card tables. Keeping that compatibility surface indefinitely would obscure the canonical schema and should be avoided.
- Database migrations are implicit in application startup rather than recorded as ordered schema versions; conditional alterations are harder to reason about as upgrade history grows.
- JSON settings and job records are flexible but weakly constrained by SQLite. Their shape, transaction behavior, and compatibility requirements are distributed across runtime code and import/export handlers.
- The parent `cyberdeck` repo and standalone Hub repo have both had application copies. The copies have diverged; packaging must always use the standalone repository, and the duplicate must not remain an active source.
- Docker artifacts were incomplete and described as experimental. They were not a reliable second deployment target.

## Target principles

1. Keep the standalone Hub repository authoritative for Hub application, user bootstrap, product configuration, and application documentation. Keep hardware research and the Windows developer deployment helper in the parent `cyberdeck` repo.
2. Keep SQLite as the authority for structured runtime metadata and relationships. Keep large binary payloads in the data filesystem. Use JSON for portable configuration/import/export and static source manifests, not as a second runtime database for editable relational records.
3. Separate HTTP adapters, domain operations, persistence, and platform adapters along feature boundaries. Extract incrementally while preserving route and import/export compatibility.
4. Make every database schema change an ordered, transactional, inspectable migration. Preserve recoverability for migrations that touch files as well as SQLite.
5. Keep host privileges behind small allowlisted operations. Admin controls must report capability and failure clearly and avoid exposing generic shell execution.
6. Keep one reviewed source path for each deployment artifact, with commit and package manifests connecting source to installed system.

## Migration and edit sequence

1. **Retire the Card compatibility layer.** Review database upgrade behavior on existing installs and all Card edit/import paths. Once those paths are stable, remove `library_subject` write-through compatibility and access subjects directly through the canonical card repository.
2. **Version schema changes.** Introduce a schema-version ledger and move future DDL/data conversions into ordered migrations. Do not combine this with a broad application rewrite.
3. **Extract by behavior.** Move request-independent logic into domain modules and repository functions, starting with acquisition/import and host capability adapters. Keep Flask routes thin and retain the existing public URLs.
4. **Finish repository boundary cleanup.** The Hub now owns the user-facing custom Debian USB bootstrap; the parent repo retains the Windows developer deploy helper. Inventory and disposition every unique legacy file and active reference before removing its nested application copy.
5. **Defer container support.** Restore Docker artifacts only after an independent container install, persistent-state, backup/restore, restart, upgrade, and optional-module acceptance.

The Card migration is the only application persistence migration in v0.2.0 scope. Module extraction is a staged direction, not a release-wide rewrite.
