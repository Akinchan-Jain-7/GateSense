# ADR-0007: Snapshot storage, and Phase 2 data model changes

- **Status:** Accepted (pending owner review in the Phase 2 PR)
- **Date:** 2026-11-21

## Context

Every gate event can carry a snapshot image. Development uses RustFS (S3-compatible, see
ADR-0002); production will use a cloud bucket (Phase 8); tests should need neither.
Building the gate-event engine also showed a few things the Phase 1 data model couldn't
record.

## Decision: snapshot storage

1. A small **`SnapshotStorage` protocol** (`save`, `load`, `delete` by key) with two
   backends: `LocalSnapshotStorage` (a folder) and `S3SnapshotStorage` (any S3-compatible
   store). `SNAPSHOT_STORAGE=local|s3` picks one at start-up.
2. **boto3** talks to S3. It is the standard client, works with RustFS, AWS, R2 and
   others, and is tested here with **moto** (an in-memory fake S3). boto3 is blocking, so
   each call runs in a worker thread.
3. The S3 backend **creates its bucket on first use**, so a fresh dev stack needs no setup.
4. Images are recognised by their **first bytes** (JPEG, PNG, WebP only), never by the file
   name or the sender's Content-Type. Size is capped by `SNAPSHOT_MAX_BYTES` (2 MB → 413).
5. Keys look like `<society>/<yyyy>/<mm>/<dd>/<event id>.jpg`, so a day's snapshots can be
   listed or purged together (retention, Phase 5). Staff download them through the API
   (`GET /gate-events/{id}/snapshot`), which checks the role and society first.

## Decision: data model changes

| Change | Why |
|---|---|
| `alerts` table | Watchlist hits must stay on the guard console until acknowledged. The brief's model had nowhere to keep them. Later phases add more alert kinds. |
| `visit_status_changes` table | "Every transition is validated and logged" (brief §2.4). See ADR-0005. |
| `gate_events.paired_event_id` (unique) | Entry/exit pairing for **resident** vehicles: an exit points at the entry it closes. Visits already pair through `entry_event_id` / `exit_event_id`. Nightly reconciliation (Phase 5) finds unpaired ones. |
| `gate_events.match_distance` | 0 = exact, 1 = fuzzy. Lets the UI flag fuzzy matches and lets us measure how often they happen. |
| `gate_events.ocr_fixes` | How many look-alike characters were swapped; useful when evaluating OCR (Phase 3). |
| `gate_events.review_reason`, `reviewed_at`, `reviewed_by_id` | The review queue needs to know *why* an event is there and whether it was handled. A partial index covers exactly the open queue. |
| Plates must use a real state/UT code | Typed and OCR plates now share one rule; it also helps OCR repair (`0L…` must be `DL…`). |

## Alternatives considered

- **Presigned S3 URLs** for snapshot downloads instead of streaming through the API. Less
  load on the API, but the URL works for anyone who has it until it expires, and RustFS
  runs on a host name the browser may not reach. Can be added in Phase 7 if needed.
- **aioboto3 / a native async S3 client.** Another dependency for a few calls per event;
  a thread is fine at our volume. Revisit if Phase 7's load test says otherwise.
- **Storing snapshots in Postgres** (`bytea`). Simple, but bloats the busiest table and
  its backups. Rejected.
- **Alerts as a flag on `gate_events`.** Works for watchlist hits only; approval timeouts
  and reconciliation findings (later phases) aren't gate events. Rejected.

## Consequences

- boto3 and moto are new dependencies (moto only for tests). moto also installs
  `cryptography`, which made PyJWT's type hints stricter; one test was adjusted.
- If the database insert fails after the snapshot is saved, the snapshot is orphaned
  (except for the duplicate race, which deletes it). Phase 5's retention job can sweep
  orphans.
