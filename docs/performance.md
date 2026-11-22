# Performance: gate-event ingestion

`POST /api/v1/gate-events` is the hot path: every car at every camera ends up here. This
page records how fast it is, how that was measured, the first bottleneck we found and
what fixing it bought. Every number below comes from a run on the machine described here;
the raw summaries are in [`loadtests/results/`](../loadtests/results/).

## How it was measured

- **Machine:** a 2-vCPU Intel Xeon cloud container with 7 GB RAM, PostgreSQL 16 and Redis 7
  on the same machine, Python 3.12. Locust runs on the same 2 cores, so absolute numbers
  are conservative; the *comparisons* are what matter.
- **Server:** one uvicorn process (no `--workers`), INFO logging on, like production.
- **Load:** [`loadtests/locustfile.py`](../loadtests/locustfile.py). 40 simulated cameras
  sending reads back to back across the 4 seeded camera keys. 60% are residents' cars
  (repeat plates, so debounce kicks in like at a real gate), 30% unknown cars and 10%
  uncertain reads; 80% carry an ~18 KB JPEG snapshot.
- **Protocol** ([`loadtests/bench.sh`](../loadtests/bench.sh)): reseed the database, start
  the API, 15 s warm-up (not counted), then three 40 s runs. The tables show the **median
  of the three**. "Before" and "after" ran from separate git worktrees of the exact
  commits, against the same database, one after the other.
- **Society size:** the demo society has 80 resident vehicles. Because matching compares
  each read with the society's plates, we also measured a bigger society (500 vehicles,
  added by `loadtests/add_vehicles.py`).

## Results

| Scenario | Throughput | p50 | p95 | p99 | Failed requests |
|---|---:|---:|---:|---:|---:|
| Before, 80 vehicles | 114.5 req/s | 290 ms | 600 ms | 800 ms | 0 of 13,343 |
| After, 80 vehicles | **149.4 req/s** (+30%) | 220 ms | **470 ms** | 650 ms | 0 of 17,596 |
| Before, 500 vehicles | 61.9 req/s | 590 ms | 1,100 ms | 1,400 ms | 0 of 7,260 |
| After, 500 vehicles | **98.0 req/s** (+58%) | 360 ms | **720 ms** | 1,000 ms | 0 of 11,558 |
| After + hardening (Phase 7 middleware), 80 vehicles | **159.1 req/s** | 200 ms | **410 ms** | 550 ms | 0 of 18,487 |

The last row is the final Phase 7 build: request ids, metrics, security headers and size
limits added work to every request, yet it is a little faster, because the same change
replaced Starlette's `BaseHTTPMiddleware` (an extra task and response copy per request)
with plain ASGI middleware.

For scale: a busy society gate sees a car every few seconds, roughly 0.1 to 1 read per
second per camera. One API process handles about 150–160 reads per second here.

## Finding the first bottleneck

**1. Is it the database or the API?** During a run, the API process sat at **90–99% of one
CPU core** while PostgreSQL used about 10%. The API was CPU-bound, so the question became
what the Python process spent its CPU on.

**2. What does the CPU do?** A `py-spy` sample of the running server showed about
**55% of CPU inside SQLAlchemy and psycopg**, our own code about 7%, and request parsing,
logging and validation only a few percent each. So the cost was database *work in
Python*, not the database itself.

**3. How much database work per read?** Counting the SQL statements one read executes
(`before_cursor_execute` hook) gave **13–14 statements in two transactions**:

- `SELECT` the camera, then `UPDATE devices SET last_seen_at` and `COMMIT`, on every
  read, all on the same four device rows: a separate transaction just to say "seen";
- a `SAVEPOINT`, the `INSERT`, a `RELEASE`, then an `UPDATE` for the normalised plate and
  another `UPDATE` for the match result;
- the matching queries: visits, **vehicles** and guest passes "with a plate of similar
  length";
- a `SELECT` for alerts, on every read, even though only watchlist hits raise alerts.

**4. The real cost: building objects nobody needed.** The matching queries loaded *full
ORM objects* for every plausible plate. Almost every Indian plate is 9–10 characters, so
"similar length" meant every active vehicle: 80 objects per read in the demo, 500 in a
bigger society. The profile's `InstanceState.__init__` and identity-map work were this.
It also explains why throughput **almost halved** going from 80 to 500 vehicles (114.5 → 61.9
req/s): the first bottleneck grows with the size of the society.

## The fix

1. **Match on `(plate, id)` pairs, load only the winner.** The fuzzy matcher only needs
   strings; it now fetches lightweight rows and loads a single `Visit` or `GuestPass` once
   the match is decided (resident matches need only the id).
2. **Write "last seen" at most once a minute** per camera, not on every read.
3. **Set the normalised plate before the `INSERT`**, so it isn't a second `UPDATE`.
4. **Look up alerts only for watchlist hits.**

Steady state is now **10 statements in one transaction** per read. The `SAVEPOINT` stayed:
it is what lets two copies of the same read arriving together store one event safely,
and it's cheap.

## A bug the load test found

The first runs had a rare **HTTP 500**: two exit reads of the same resident car at the same
instant (for example two exit cameras) both found its entry open and both paired with it;
the second hit the unique constraint on `paired_event_id`. The fix locks the entry row
(`SELECT … FOR UPDATE`) before checking whether it is closed, so the second exit waits,
sees it closed, and stays unpaired (reconciliation reports it). A regression test
(`backend/tests/test_concurrency.py`) runs the race with real, separate database
connections; it failed 3 times out of 3 before the fix and passes after.

## What would come next

- **More processes, on more cores.** See "Multiple API workers" below: on this 2-vCPU
  machine a second worker added nothing, because there was no idle core to give it.
- **Exact match first.** Most reads are exact plate matches; an indexed lookup could skip
  the fuzzy scan entirely, which would remove the remaining dependence on society size.
- **Cache society settings** for a few seconds instead of reading them on every read.

## Multiple API workers (measured later, same machine)

Same setup as above (80 vehicles, 40 users, median of three 40-second runs), with the
machine otherwise idle, run back to back:

| API processes | Requests/s | p50 | p95 | p99 | Failed |
|---|---|---|---|---|---|
| 1 (`--workers 1`) | 172.5 | 180 ms | 360 ms | 480 ms | 0 of 20,215 |
| 2 (`--workers 2`) | 169.7 | 200 ms | 350 ms | 420 ms | 0 of 20,531 |

(Raw numbers: `loadtests/results/workers1-80.json`, `workers2-80.json`. The one-worker
figure is a little higher than the 159.1 req/s measured in Phase 7 on the same code path:
run-to-run machine variance, which is why both rows here come from one session.)

**No gain, and why.** A `top` sample during the two-worker run showed the CPUs 0.6% idle:
the two API processes at about 73% and 67%, Locust at 18%, PostgreSQL and Redis sharing
the rest. With one worker, the API process already had a core to itself while Locust and
PostgreSQL used the other. A second worker only competes with them for the same two
vCPUs. More workers pay off when there are idle cores: on the deployment server,
`WEB_CONCURRENCY` should be about the number of cores *left after PostgreSQL*, and the
load generator should run on a different machine before any multi-worker number is
quoted.

The first attempt at this measurement showed 99.8 req/s and 1,534 failures. The cause was
leftover processes (a frontend preview server, Chrome from the browser tests, an older API
process on the same port) competing for the CPU, not the code. It is a reminder to check
the machine is idle before trusting a benchmark.

## Reproducing

```bash
# Postgres + Redis running, backend migrated (see CONTRIBUTING.md)
cd loadtests && uv sync
echo "LOADTEST_DATABASE_URL=postgresql://gatesense:<password>@127.0.0.1:5432/gatesense" > .env.local
./bench.sh mine ../backend          # 80 vehicles
./bench.sh mine-500 ../backend 420  # 500 vehicles
WORKERS=2 ./bench.sh mine-w2 ../backend  # two API processes
```

`bench.sh` reseeds the database and rotates camera keys: never point it at real data.
It lifts the per-camera rate limit (`DEVICE_RATE_LIMIT`), since 40 simulated cameras on
four keys send far more than real cameras would.
