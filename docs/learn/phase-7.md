# Phase 7 study guide: hardening, offline mode and performance

## What we built and why

Phase 7 made GateSense ready for the real world. The camera worker now keeps plate reads
in a small SQLite database when the internet is down and sends them, in order, when it
comes back. The API defends itself: it limits login attempts and camera floods, refuses
huge uploads, adds security headers, and only accepts requests from the real web app.
Every request gets an id that appears in every log line, and `/metrics` exposes numbers
Prometheus can graph. Finally, we load-tested the busiest endpoint, found what was slow by
*measuring* (not guessing), fixed it and recorded before/after numbers. The load test also
found a real concurrency bug, now fixed and covered by a test.

## Key concepts, simply

**Offline buffer (store and forward).** If you can't deliver a letter, keep it in a box
and post it later, oldest first. SQLite is the box: one file, survives power cuts.

**Idempotency (again).** Sending the same read twice must not create two events. Because
the server recognises repeats (same device + plate + capture time), the camera can safely
resend anything it's unsure about.

**Rate limiting, fixed window.** Count requests per person per minute in Redis
(`INCR`, with the key expiring after the minute). Over the limit → HTTP 429 and a
`Retry-After` header saying when to come back.

**Fail open vs fail closed.** If the limiter itself breaks (Redis down), do we block
everyone (closed) or let requests through (open)? For login and cameras we chose open: a
broken limiter shouldn't lock the society out of its own gate.

**Security headers.** Instructions to the browser: don't guess file types (`nosniff`),
don't show us inside someone else's frame (`X-Frame-Options`), only run scripts we allow
(`Content-Security-Policy`), always use HTTPS (`HSTS`). The visitor page allows exactly
its own inline script, identified by its SHA-256 hash.

**CORS.** Browsers only let a web page call an API on another origin if the API says so.
We allow only our web app's origin and only the methods and headers it uses.

**Request id and ContextVar.** A random id per request, returned to the client and added
to every log line. A `ContextVar` is like a global variable that each request (asyncio
task) sees separately, so deep code can log the id without passing it around.

**Prometheus metrics.** A plain-text page of counters and histograms that Prometheus
fetches every few seconds. Labels must have few values: we use the route *template*
(`/api/v1/visits/{visit_id}`), never the raw path with ids.

**CPU-bound vs I/O-bound.** If the process is at 100% CPU, it's CPU-bound: faster disks
or databases won't help; doing less work per request (or adding processes) will.

**Little's law.** Requests in flight = throughput × time per request. 40 cameras at 150
requests/second means each request takes about 0.27 s, because they queue for the CPU.

**Row lock (`SELECT … FOR UPDATE`).** "I'm about to change this row; others wait." It
stops two exits from both closing the same entry.

## Files to read, in order

1. `anpr/gatesense_anpr/buffer.py`: the offline queue and the sender that uses it.
2. `anpr/tests/test_buffer.py`: an outage, a restart and a rejected read, end to end.
3. `backend/app/services/rate_limit.py`: the fixed-window limiter in 30 lines.
4. `backend/app/core/middleware.py`: request ids + metrics, security headers, size limits.
5. `backend/app/core/metrics.py` and `GET /metrics` in `backend/app/api/system.py`.
6. `backend/app/api/public.py`: the hashed Content-Security-Policy for the visitor page.
7. `loadtests/locustfile.py` and `loadtests/bench.sh`: how load was generated and measured.
8. `docs/performance.md`: the investigation, step by step, with the numbers.
9. `backend/app/services/gate_events.py`: `_known_plates` (plate/id pairs) and
   `_close_resident_entry` (the row lock).
10. `backend/tests/test_concurrency.py`: reproducing a race with two real connections.

## Decisions and the alternatives we rejected

See [ADR-0013](../adr/0013-hardening-and-observability.md).

- **SQLite buffer** over a JSON-lines file (no atomic writes) or a local Redis (another
  service to run at the gate).
- **Own 30-line limiter** over a library (slowapi): easy to explain, one Redis round trip.
- **Plain ASGI middleware** over `@app.middleware("http")`, which adds overhead per request.
- **Fix the measured bottleneck** (ORM objects in matching) rather than the first guess
  (the device heartbeat, which only gave ~10%).
- **Kept the savepoint** around the insert even though it costs two statements: it's what
  makes simultaneous duplicate uploads safe.

## Likely interview questions

1. **What happens to plate reads when the internet goes down?** They go into a SQLite
   queue at the gate and are sent oldest-first when it's back; new reads wait behind old
   ones so entries arrive before exits. Resending is safe because the server is idempotent.
2. **How did you find the bottleneck?** Measured: the API was at ~100% CPU while
   PostgreSQL idled; py-spy showed ~55% of CPU in SQLAlchemy/psycopg; counting statements
   showed 13–14 per read and every vehicle loaded as an ORM object on every read.
3. **What did the fix achieve?** +30% throughput and p95 600 → 470 ms with 80 vehicles;
   +58% and p95 1,100 → 720 ms with 500 vehicles (median of three runs each).
4. **What concurrency bug did load testing reveal?** Two simultaneous exits both paired
   with one entry; the second violated a unique constraint (500). Fixed with
   `SELECT … FOR UPDATE`, and a test with two real connections reproduces it.
5. **Why rate-limit per IP *and* per account?** Per account stops guessing one person's
   password from many IPs; per IP stops one machine trying many accounts.
6. **Why does the limiter fail open?** If Redis is down, blocking every login and camera
   would take the gate offline; briefly not limiting is the lesser harm.
7. **Why route templates as metric labels?** Each label value is a separate time series;
   raw paths with ids would create millions and overwhelm Prometheus.
8. **What does the request id give you?** One id in the response and on every log line of
   that request: a user's bug report ("request id abc…") finds the exact logs.
9. **Why a hash in the CSP instead of `'unsafe-inline'`?** The hash allows only that exact
   script; an injected script has a different hash and is blocked.
10. **How would you scale further?** Run several API processes (it's CPU-bound), try an
    exact-match lookup before the fuzzy scan, and cache society settings briefly.

## Exercise

Add a metric `gate_events_review_total` that counts reads sent to the guard's review queue,
labelled by `reason` (`low_confidence`, `unreadable`, `ambiguous_match`). Increment it
where `_send_to_review` is called, check it appears at `/metrics` in a test, and think
about why `reason` is a safe label but `plate` would not be.
