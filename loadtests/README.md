# Load tests

[Locust](https://locust.io) load tests for gate-event ingestion, the API's hot path.
Results, method and the bottleneck analysis: [docs/performance.md](../docs/performance.md).

```bash
cd loadtests && uv sync
# one-off run against a running API (seeded with `uv run python -m app.seed --reset`)
uv run locust --headless -u 40 -r 20 -t 60s --host http://127.0.0.1:8000 --only-summary
# the repeatable benchmark used for docs/performance.md (reseeds the database!)
./bench.sh <label> ../backend [extra vehicles]
```

- `locustfile.py`: 40 simulated cameras with a realistic mix of reads and snapshots.
- `bench.sh`: reseed, start one API process, warm up, three runs, median.
- `summarise.py`: turns Locust's CSVs into `results/<label>.json`.
- `add_vehicles.py`: grows the demo society, to measure a bigger one.

Never point these at real data: they reseed the database and rotate camera keys.
