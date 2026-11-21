# Phase 2 study guide: Gate event engine

## What we built and why

This is the brain of GateSense. A camera now sends `POST /api/v1/gate-events` with the
plate text OCR read, its confidence, the capture time and a photo. The backend throws away
exact retries, repairs OCR mistakes using the grammar of Indian plates, folds repeated
reads of the same car into one event, saves the photo (local folder or S3), and then
decides what the read means: a watchlisted vehicle (red alert), an unsure read (guard
review queue), a resident's car (entry or exit logged, exits paired with entries), an
expected visitor (their visit moves `approved → inside`, later `inside → exited`), or an
unknown vehicle. Visits change status only through a small, fully tested state machine,
and every change is written to a history table. Guards get APIs for the event list,
snapshots, the review queue (their corrections are saved as training data for the OCR
model) and alerts. Phase 3 plugs the real camera + ML pipeline into this endpoint; Phase 4
adds visitor registration and approvals on top of the state machine.

## Key concepts, explained simply

**OCR look-alikes.** OCR often confuses characters that look the same: `O`/`0`, `I`/`1`,
`B`/`8`, `S`/`5`, `Z`/`2`. On its own, `DLO1AB1234` is ambiguous, but an Indian plate has
a fixed grammar: 2 state letters, 1–2 district digits, 0–3 series letters, 1–4 number
digits. In `DLO1…` the third character sits where a digit must be, so the `O` must be `0`.

**Trying every layout.** The tricky part is that layouts differ in length (`DL3CAB1234`
vs `KA05MN0042`). So `read_ocr_plate` tries *every* layout that fits the text, counts how
many characters it had to swap ("fixes"), adds a small penalty for unusual shapes, and
keeps the lowest score. Real-world rules prune bad guesses: the state code must exist
(`0L…` is `DL…`, because `OL` isn't a state), and RTOs never put I, O or Q in a series.

**Edit distance (Levenshtein).** The number of single-character inserts, deletes or
swaps needed to turn one string into another. `UP16AB1284` → `UP16AB1234` is 1. We accept a
match at distance ≤ 1, but only if exactly *one* known plate is that close. If two are
equally close, we don't guess: the read goes to the guard.

**Idempotency.** Doing something twice has the same effect as doing it once. Cameras
retry uploads when the network blips. Each read gets a fingerprint (`event_hash` =
SHA-256 of device + plate text + capture time) with a UNIQUE constraint in Postgres, so a
retry finds the original event instead of creating a second one.

**Debouncing.** Collapsing a burst of repeated signals into one. A waiting car appears in
dozens of frames. We remember in Redis, per lane and plate, when we last saw it; a read
within 30 seconds of the previous one joins the same event. The window *slides* (each read
pushes it forward) and uses the camera's *capture* time, so buffered reads replayed later
are still judged correctly.

**Atomic operations and Lua in Redis.** "Read the last-seen time, decide, write the new
time" must happen as one step, or two requests arriving together could both think they're
first. Redis runs a Lua script as one uninterrupted operation, which gives us that.

**Fail open vs fail closed.** When a dependency is down, do you allow or block? Our
debounce *fails open*: if Redis is down, reads are accepted (maybe a duplicate event).
Blocking would mean missing cars at the gate, which is worse.

**State machine.** A fixed set of statuses plus a table of allowed moves:
`(INSIDE, exit) → EXITED` is allowed; `(EXITED, enter)` is not and raises an error. Putting
every rule in one dictionary makes illegal histories impossible and the rules easy to read
and test. The module is *pure* (no database), so all 56 status/trigger pairs are tested in
milliseconds.

**Storage abstraction (a Protocol).** The engine calls `storage.save(key, data)` without
knowing if that's a folder or an S3 bucket. Python's `Protocol` describes the methods both
backends provide. Switching is a setting (`SNAPSHOT_STORAGE=s3`).

**Magic numbers (file signatures).** Every JPEG starts with bytes `FF D8 FF`, every PNG
with `89 50 4E 47…`. We check those bytes instead of trusting the file name or the
uploader's `Content-Type`, which an attacker controls.

**Pairing.** For residents, an exit event points at the entry it closes
(`paired_event_id`, unique). Unpaired exits ("left without entering") and entries that
are never closed are data-quality signals the nightly reconciliation job reports (Phase 5).

## Files to read, in order

1. `backend/app/services/plates.py`: plate cleaning, `read_ocr_plate` (layouts, scoring),
   `bounded_edit_distance`, `closest_plates`. Notice how the penalties are explained.
2. `backend/tests/unit/test_plate_reader.py`: the 50-case table. Read the tricky ones
   (`KAO5MNOO42`, `0L01AB1234`, `UP16A01234`) and work out *why* each answer wins.
3. `backend/app/services/visit_state.py`: the transition table and `apply_transition`.
   Notice there is no database code at all.
4. `backend/tests/unit/test_visit_state.py`: how every legal and illegal move is tested.
5. `backend/app/services/visits.py`: the only place a visit's status is saved, together with
   its history row.
6. `backend/app/services/debounce.py`: the Lua script and the fail-open `except`.
7. `backend/app/services/storage.py`: the Protocol, the two backends, image detection.
8. `backend/app/services/gate_events.py`: the whole pipeline. Read `ingest_read` top to
   bottom, then `apply_match`; notice the order of checks.
9. `backend/app/api/v1/gate_events.py`: multipart form fields, the 413 size check, why
   `review-queue` is declared before `/{event_id}`.
10. `backend/alembic/versions/20261121_b6371bdaf779_gate_event_engine.py`: what changed in the
    schema (two tables, six columns, a partial index).
11. `backend/tests/api/test_gate_scenario.py`: a whole morning at the gate in one test; the
    best summary of what Phase 2 does.
12. `docs/adr/0005` to `0008`: the reasons behind each decision.

## Decisions made and alternatives rejected

| Decision | Rejected alternative | Why |
|---|---|---|
| Try every plate layout and score them | One regex with `[A-Z0O]`-style classes | A regex can't say "this is a letter only if the district has 2 digits" |
| Fuzzy match within 1 edit; ambiguous → review | Distance 2, or "pick the first" | Real plates often differ by 1–2 characters; a wrong match opens the gate for the wrong car |
| Watchlist checked even on unsure reads | Skip unsure reads entirely | A false alarm costs a glance; a missed flagged vehicle costs much more |
| Unsure reads do nothing automatically | Act on the best guess | Never open a gate or close a visit on a guess; a guard confirms in two taps |
| Debounce in Redis, sliding, by capture time | Fixed window; server arrival time; a Postgres query | Waiting cars, offline replay, and a cheaper hot path |
| Idempotency via a UNIQUE hash in Postgres | Only the Redis debounce | The database constraint also holds when Redis is down or under races |
| State machine as a plain dict in a pure module | A state-machine library; DB triggers | Ten rules don't need a framework; Python is easier to test and explain |
| `alerts` and `visit_status_changes` tables | Flags on existing rows | Alerts need acknowledging; history needs one row per change |
| boto3 + moto for S3 | Hand-written S3 calls; a real S3 in unit tests | Standard client; moto fakes S3 in memory, the CI compose job tests real RustFS |
| Snapshots streamed through the API | Presigned S3 URLs | Role and society checks stay in one place; revisit for performance in Phase 7 |

## Likely interview questions

1. **How do you handle OCR mistakes like O vs 0?**
   Indian plates have a known grammar. I try every valid layout for the text's length,
   swap look-alike characters only where that layout needs the other kind, and pick the
   reading with the fewest swaps and the most common shape. Then I fuzzy-match against
   known plates to catch what's left.

2. **What if a plate is one character away from two residents' cars?**
   We don't guess. The event goes to the guard review queue as `ambiguous_match`; the
   guard types the right plate and matching runs again.

3. **What's the difference between your idempotency and your debounce?**
   Idempotency catches the *same* read sent twice (a retry), using a unique hash in
   Postgres. Debounce catches *different* reads of the same car seconds apart (more frames),
   using a sliding window in Redis.

4. **Why use capture time instead of server time for debouncing?**
   An offline camera may upload an hour of reads in a few seconds. With server time,
   two visits an hour apart would be merged into one.

5. **What happens if Redis goes down?**
   Debounce fails open: reads are accepted and logged, so we might store a few extra
   events. Exact retries are still caught by the database's unique constraint. `/ready`
   reports Redis as down.

6. **Why a state machine for visits?**
   Many actors change a visit (guard, resident, cameras, timers). One table of legal moves,
   one function that applies them and one writer that logs them make impossible states
   impossible, and every rule is tested.

7. **How do you stop two identical uploads from creating two events at the same instant?**
   Both may pass the "already exists?" check, but the UNIQUE constraint on `event_hash`
   rejects the second insert. We catch that, return the winner, and delete the loser's
   snapshot. There's a test that simulates exactly this race.

8. **How do you validate uploaded images?**
   By their first bytes (JPEG/PNG/WebP signatures), never by name or Content-Type, with a
   2 MB cap (413 if larger) read without loading an unbounded file into memory.

9. **Why is the watchlist checked before the confidence threshold?**
   Asymmetric cost: a false alarm costs the guard a glance; missing a flagged vehicle can
   cost much more. Unsure watchlist reads raise the alert *and* go to review.

10. **How would this scale to many societies or many vehicles?**
    Exact lookups use indexed `plate_normalized`; fuzzy candidates are pre-filtered by
    plate length in SQL. For tens of thousands of plates per society I'd move fuzzy search
    into Postgres (`pg_trgm`) or keep an in-memory index; Phase 7's load test measures it.

## Exercise

Without running anything, decide what each of these OCR reads becomes, how many fixes it
needs, and why. Then add them to `READABLE` in `tests/unit/test_plate_reader.py` and run
`uv run pytest tests/unit/test_plate_reader.py`:

- `HR5IDK8337` (careful: is that `I` a district digit or a series letter?)
- `23BHO0O1A`
- `INDKA05MNOO42`

Bonus: in `test_gate_scenario.py`, add a step where the resident's car is read on the exit
lane 20 seconds after the 08:30 exit (minute `90.33`). What `status` should the API return,
and why? What changes if it's read 60 seconds after instead, and is that new event paired?
