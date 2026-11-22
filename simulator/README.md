# Simulator

Demo traffic generator. It keeps the live demo busy by doing what real cameras, a guard
and residents would do, **through the public API only**: it never touches the database.

Things it does, at a realistic rate for the time of day (busy 8–10 am and 6–9 pm IST):

| What happens | Share of arrivals | Through which API |
|---|---|---|
| A resident's car leaves or comes home | 50% | camera reads (`POST /gate-events`) |
| An unknown visitor arrives: the camera reads the plate, the guard registers them, the resident approves (72%), denies (8%) or doesn't answer (20%, so the guard decides after the 3-minute timeout) | 30% | camera, `POST /visits`, approval decision |
| A resident creates a guest pass; the guest arrives and is let in automatically | 7% | `POST /guest-passes`, camera |
| A blurry read (low confidence, one character wrong) goes to the review queue | 10% | camera |
| A watchlisted car shows up (at most once every 45 minutes) | 3% | camera |

Visitors leave after a usual stay for their category. About 1 in 12 stays too long, and the
real Celery workers then run the escalation ladder (emails, then a "call the resident" task).
Once a minute the simulated guard clears items that are a few minutes old, such as call
tasks, alerts and review items, so the console shows a mix of new and handled work.

## Run it

```bash
cd simulator
uv sync
uv run gatesense-sim --api http://127.0.0.1:8000           # real time
uv run gatesense-sim --speed 20 --minutes 5 --seed 1       # busier, for a quick look
```

It needs a backend with the demo data (`uv run python -m app.seed` in `backend/`). At start
it signs in as the demo admin and **rotates every camera key** to get keys it can use. When
the demo is reset (nightly, or with the admin's "Reset demo" button), its sign-ins and keys
stop working, so it starts over by itself.

| Setting (flag / environment) | Default | Meaning |
|---|---|---|
| `--api` / `SIM_API_URL` | `http://127.0.0.1:8000` | Backend base URL |
| `--password` / `SIM_PASSWORD` | `GateSense@123` | The demo password (`DEMO_PASSWORD`) |
| `--admin` / `SIM_ADMIN_EMAIL` | `admin@example.com` | Account used to rotate camera keys |
| `--guard` / `SIM_GUARD_EMAIL` | `guard@example.com` | The guard who registers visitors |
| `--speed` / `SIM_SPEED` | `1` | Time compression: 2 = twice the arrivals, stays half as long |
| `--tick` / `SIM_TICK_SECONDS` | `5` | How often it wakes up |
| `--seed` | random | Repeatable runs |
| `--minutes` | forever | Stop after this long |

`--speed` only compresses the simulator's own clock. The server's timers (the 3-minute
approval timeout, visit time limits) still run in real time, so overstays and escalations
only appear at a speed close to 1, which is what the live demo uses.

## Tests

```bash
uv run pytest --cov     # against a fake API (httpx MockTransport); no server needed
```
