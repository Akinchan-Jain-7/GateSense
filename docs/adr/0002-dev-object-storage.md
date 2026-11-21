# ADR-0002: Local S3-compatible storage (RustFS instead of MinIO)

- **Status:** Proposed (waiting for the owner's OK)
- **Date:** 2026-11-21

## Context

Every gate event stores a plate snapshot image (`CLAUDE.md` §2, item 11). In production this
goes to an S3-compatible bucket; locally the brief names **MinIO** as the stand-in.

Since the brief was written, MinIO changed course:

- In October 2025 MinIO stopped publishing pre-built binaries and Docker images for its
  free community edition ("source only"), and later removed the images from Docker Hub.
- The community repository has since been archived, so it gets no more security fixes.

Using MinIO now means either building it from source ourselves or trusting an unofficial
third-party image of an unmaintained server.

## Decision (proposed)

Use **[RustFS](https://github.com/rustfs/rustfs)** (`rustfs/rustfs:1.0.6`) as the local
S3-compatible store. It is open source (Apache-2.0), actively maintained, has stable 1.0
releases, speaks the S3 API on port 9000 and has a web console on port 9001, just like MinIO.

The backend only ever talks the **S3 API** (through the storage abstraction built in
Phase 2), so the choice of local server can change at any time without code changes.

## Alternatives considered

| Option | Why not (for now) |
|---|---|
| Last official MinIO image (Sept 2025) | Unmaintained; known unpatched CVEs. |
| Community MinIO rebuilds | Unofficial publishers; still the archived codebase. |
| SeaweedFS / Garage | Good projects, but more setup than a one-container dev stand-in. |
| Local disk only | Supported anyway as a storage mode, but doesn't exercise the S3 path we use in prod. |

## Consequences

- `docker-compose.yml` has a `storage` service instead of `minio`.
- `.env.example` uses neutral names (`S3_ACCESS_KEY`, `S3_SECRET_KEY`), so swapping the
  server later only touches the compose file.
- If the owner prefers MinIO anyway, the swap is a few lines in `docker-compose.yml`.
