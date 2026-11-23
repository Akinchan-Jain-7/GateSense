# GateSense interview guide

How to talk about this project in an interview: a 2-minute pitch, a walkthrough you can
draw on a whiteboard, the hardest questions you're likely to get with honest answers, and
what you'd do differently. Every number here comes from a measurement in the repo; say
where it comes from if asked.

## The 2-minute pitch

> "GateSense is a gate management system for housing societies, the kind with a guard at
> the gate writing car numbers in a register. A camera at the gate reads number plates
> with a YOLOv8 detector and OCR. Residents' cars are let in and logged automatically. An
> unknown visitor is registered by the guard in two taps, and the flat gets an approve or
> deny request in real time, in the web app and on Telegram; if nobody answers in three
> minutes, the guard decides. Visitors who overstay get emailed, reminded and then turned
> into a 'call the resident' task for the guard.
>
> The backend is FastAPI with PostgreSQL, Redis and Celery; the frontend is React with
> TypeScript. Visits are a state machine, so a visitor can't jump from 'waiting for
> approval' to 'left'. The camera worker keeps reads in SQLite when the internet drops and
> replays them in order.
>
> I load-tested the busiest endpoint, plate-read ingestion, found the bottleneck by
> profiling and cut database statements per read from 13–14 to 10, which raised throughput
> about 30% with 80 vehicles and about 58% with 500. The load test also exposed a race
> between entry and exit reads, which I fixed with row locking and a regression test. It's
> tested end to end in CI (about 500 backend tests at 96% coverage, browser tests for the
> three key journeys, and automated accessibility checks) and the whole thing deploys as
> one Docker Compose stack."

Short version (30 seconds): the first paragraph plus "FastAPI, PostgreSQL, Redis, Celery,
React; tested in CI; one Docker Compose stack."

## Whiteboard walkthrough

Draw this left to right, then follow one car through it:

```
Camera → ANPR worker (YOLO + OCR, SQLite buffer) → HTTPS → Caddy → FastAPI → PostgreSQL
                                                                    ↕ Redis ↔ Celery worker/beat
                                              Browser ← WebSocket ← (Redis pub/sub)
```

1. The camera worker posts a plate read with a confidence score and a photo.
2. The API drops duplicates (Redis cooldown + unique event hash), repairs OCR mistakes by
   position, and fuzzy-matches against residents, guest passes and the watchlist.
3. Unknown car → guard registers the visitor → approval request → Redis pub/sub →
   WebSocket to the resident + Telegram. A Celery task fires after 3 minutes if unanswered.
4. Approved car at the gate → visit goes `approved → inside`; the timer starts.
5. Celery Beat runs the overstay ladder every minute; each step has an idempotency key so
   it happens exactly once.
6. Exit camera → visit `exited`.

## The 10 hardest likely questions

**1. Why a state machine for visits? Isn't it over-engineering?**
A visit has eight statuses and several actors changing them (camera, guard, resident,
timers). Without one place that says which changes are legal, a late camera read or a
double click can put a visit in an impossible state. The machine is a dictionary of
allowed `(status, trigger) → status`, one function applies it and writes history, and an
illegal change is a 409. It's 60 lines and makes every other piece simpler to test.

**2. The same car is read 20 times as it drives past the camera. How do you not create 20
events?**
Two layers. The camera worker votes across frames and sends one read per car. The server
also keeps a short cooldown per plate per lane in Redis (`SET NX` with expiry), and an
exact repeat from a retry is rejected by a unique hash of device, plate and capture time.
So retries are safe, which matters because the worker resends after network failures.

**3. OCR reads `DL0lAB1234`. How do you get `DL01AB1234`?**
Indian plates have a grammar: two letters, two digits, one to three letters, four digits
(plus the BH series). Characters that look alike (`O/0`, `I/1`, `B/8`, `S/5`, `Z/2`) are
swapped by position: a letter where a digit must be becomes the digit. Then a fuzzy match
against known plates with a bounded edit distance catches the rest, and low-confidence
reads go to a human review queue instead of guessing.

**4. How did you find the performance bottleneck?**
Measured, didn't guess. Locust load test of plate ingestion, then py-spy to see where CPU
went: most of it was in SQLAlchemy and psycopg, so I counted SQL statements per request.
There were 13–14 in two transactions; loading only the columns needed for matching and
removing a redundant query got it to 10 in one. Median throughput went from 114.5 to 149.4
requests/s (80 vehicles) and 61.9 to 98.0 (500 vehicles), with zero failures, on a 2-core
machine. Details and the raw files are in `docs/performance.md`.

**5. Tell me about a bug you found.**
Under load, an entry and an exit read for the same car could arrive together and both
try to close or open the same visit, causing a 500. Two transactions each read "no open
entry" and wrote. I fixed it with `SELECT … FOR UPDATE` on the row being paired, and added
a test that races two real database connections; it failed before the fix and passes after.

**6. What happens when the gate's internet goes down?**
The camera worker writes reads it can't deliver into SQLite (WAL mode, survives power
cuts) and replays them oldest first when the server is back, so entries arrive before
exits. Because the server is idempotent, a replayed read that already arrived is simply
recognised. A read the server rejects for good (a 4xx) moves to a separate table so it
can't block the queue.

**7. How do you make sure a reminder email isn't sent twice if a job runs twice?**
Every notification row has a unique idempotency key like `visit:<id>:reminder:resident:<id>`;
inserting it twice does nothing (`ON CONFLICT DO NOTHING`). A dispatcher sends pending rows,
claimed with `FOR UPDATE SKIP LOCKED` so two dispatchers can't send the same row, and
retries failures with exponential backoff. Telegram approval messages use the same queue
and are cancelled if the resident already answered.

**8. How does real time work with several API processes?**
The API doesn't push to sockets directly. It publishes an event to a Redis channel (one
per society, one per user); every WebSocket connection, whichever process it's in,
subscribes to its channels. The browser treats each event as "this list is stale" and
refetches, so the server doesn't need to know what's on screen. If the socket drops, the
client reconnects with exponential backoff and jitter and refetches everything once.

**9. How accurate is the plate detector, and how do you know?**
Trained on openly licensed Indian plate photos and tested on a separate dataset from a
different source, so near-duplicate images can't inflate the score. The exact numbers are
in `anpr/eval/results/detector_comparison.md`. Be honest about the limits: a few hundred
training images, and the test set isn't night or rain specific, so per-condition accuracy
still needs our own labelled photos (that's notebook 02).

**10. What would break first with 50 societies?**
Throughput per process is CPU-bound in Python; a second worker on a 2-core box didn't help
because the CPU was already full, so scaling needs more cores or more machines. After that,
PostgreSQL: the per-read fuzzy matching scans a society's plates. Next steps would be an
exact-match index lookup before fuzzy matching, caching society settings, and the
`society_id` column (already on every table) to shard by society.

## What I'd do differently

- **Start with labelled data earlier.** The ML side waited on datasets; collecting and
  labelling our own gate photos (day, night, rain, two-wheelers) in week one would have
  given per-condition accuracy instead of one overall number.
- **Contract tests between the camera worker and the API** (a shared schema) rather than
  only end-to-end tests.
- **Fewer, larger services sooner?** No: one API plus Celery was right. But I'd add tracing
  (OpenTelemetry) from the start; request ids in logs only go so far.
- **Accessibility checks from the first screen**, not after the UI was built: the automated
  check found three issues that would have been cheaper to avoid.
