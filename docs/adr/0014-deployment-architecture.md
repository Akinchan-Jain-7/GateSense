# ADR-0014: Deployment architecture

- **Status:** Proposed (waiting for the owner to choose a host)
- **Date:** 2026-11-22
- **Phase:** 8

## Context

The live demo must stay up around the clock: the API, a Celery worker and Celery Beat
(escalation every minute, approval timeouts, nightly jobs), PostgreSQL, Redis, and the
traffic simulator so recruiters always see activity. The ANPR worker is heavy (YOLO + OCR)
and belongs next to the cameras. The budget is zero or close to it, and the owner has to
be able to run and explain the whole thing.

The brief suggested a mix of free platforms (Render / Railway / Fly.io, Vercel, Neon or
Supabase, Upstash). Checked in November 2026, those free tiers don't fit an always-on
worker: Render's free plan has no background workers and free web services sleep after
15 minutes idle; Upstash's monthly command allowance and Neon's monthly compute hours run
out under a Celery worker and a simulator that never stop. Splitting the frontend onto
another host also means CORS and two deploys.

## Decision (proposed)

1. **One server, one Compose file.** `docker-compose.prod.yml` runs PostgreSQL, Redis,
   Mailpit, a one-shot `migrate` step, the API, the worker, beat, Caddy and (demo only) the
   simulator. The same file is the self-hosting story for a real society.
2. **Host:** Plan A, Oracle Cloud Always Free Arm VM (2 OCPU / 12 GB in 2026); Plan B, a
   small paid VPS (2 vCPU / 4 GB). The owner picks; the setup steps are identical after
   the server exists (`docs/deployment.md`).
3. **Caddy is the only public entry point.** It serves the built React app, forwards
   `/api`, `/visit` and `/docs` to the API, gets and renews the Let's Encrypt certificate
   by itself (a free `sslip.io` name works without a domain), sets a strict CSP for the app
   and hides `/metrics`. One origin means no CORS and one certificate.
4. **Images built by CI, not on the server.** On every green `main`, GitHub Actions builds
   amd64 + arm64 images and pushes them to GHCR (tagged `latest` and the commit SHA). The
   server only pulls. Rollback = start an older SHA.
5. **Deploy over SSH when configured.** The deploy job runs only if the `DEPLOY_*` secrets
   exist; the server's host key is pinned (`DEPLOY_KNOWN_HOSTS`). Until then CI just
   publishes images.
6. **Safety by default:** non-root containers, healthchecks, only ports 80/443 published,
   `DEMO_MODE=false` unless the operator turns it on, and the nightly demo reset does
   nothing outside demo mode. A real society starts with `python -m app.setup_society`.
7. **ANPR stays at the edge**, talking HTTPS with a camera key, with its offline buffer
   (ADR-0013). The cloud runs the simulator instead of real cameras.

## Alternatives rejected

- **Several free platforms:** no always-on worker for free, monthly caps, two origins.
- **Kubernetes (k3s) on the VM:** more to learn and explain than the project needs for one
  server; Compose covers healthchecks, restarts and ordering.
- **Vercel for the frontend:** works, but adds CORS, a second deploy and a second URL for
  no gain once Caddy serves the static files.
- **Building images on the server:** slow on a small VM, and different from what CI tested.

## Consequences

- One machine is a single point of failure: fine for a demo, and the backup and rollback
  steps are documented. A real deployment would add off-site database backups.
- Oracle's free Arm capacity can be unavailable; Plan B costs a few euros a month.
- The production stack is tested end to end in CI (images, Caddy, simulator), but a real
  certificate on a real host is only tested once the owner creates the server.
