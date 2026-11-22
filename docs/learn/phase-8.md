# Phase 8 study guide: Docker and deployment

## What we built and why

Phase 8 turns the project from "runs on my laptop" into "runs on a server for anyone".
The backend and frontend each got a production Docker image: small, without development
tools, running as a normal user instead of root, with a health check. One Compose file
(`docker-compose.prod.yml`) starts the whole system on a single server, with Caddy in
front to serve the web app and get a free HTTPS certificate automatically. GitHub Actions
now builds those images for both Intel and Arm servers on every merge and, once the server
details are added as secrets, updates the server by itself. A traffic simulator keeps the
public demo busy with realistic cars, visitors and approvals, and the demo resets itself
every night. The actual server waits on the owner choosing a host; everything up to that
point is built and tested in CI.

## Key concepts, simply

**Docker image vs container.** An image is a frozen box with the program and everything it
needs. A container is that box running. Same image on your laptop and the server = no
"works on my machine".

**Multi-stage build.** One Dockerfile, several steps. A "build" stage has the heavy tools
(uv, Node) and makes the app; the final stage copies only the result into a fresh, small
image. Smaller image = faster to pull and less to attack.

**Build targets (`dev` and `prod`).** The same Dockerfile can stop at different stages.
Development uses `target: dev` (live reload, code mounted from your disk); production uses
`target: prod`.

**Non-root user.** By default a container runs as root. If someone breaks into the app,
root inside the container can do much more damage. We create a user with no shell and run
as that.

**Health check.** A small command Docker runs every few seconds (`GET /health`). Compose
waits for "healthy" before starting things that depend on it, and restarts what dies.

**Reverse proxy (Caddy).** The one program facing the internet. It receives every request
and passes it on: files for the web app, `/api` to the API. It also does HTTPS: it asks
Let's Encrypt for a certificate and renews it before it expires, with no setup.

**One origin.** If the app and the API share an address (`https://x.sslip.io` and
`https://x.sslip.io/api`), the browser treats them as one site: no CORS rules needed.

**Container registry (GHCR).** A place to store images, like GitHub for code. CI pushes
images there; the server pulls them. Each image is tagged with the commit it came from, so
going back to an older version is just "run the older tag".

**Multi-architecture image.** Intel/AMD servers (amd64) and Arm servers (arm64, e.g.
Oracle's free VM) need different binaries. `docker buildx` builds both and stores them
under one name; each server pulls the right one.

**CI/CD.** CI (continuous integration) = every change is built and tested automatically.
CD (continuous delivery/deployment) = after the tests pass, the new version is published
and rolled out automatically.

**Secrets.** Passwords and keys never go in git. On the server they live in `.env.prod`
(git-ignored); for GitHub Actions they live in the repo's encrypted secrets.

## Files to read, in order

1. `docs/deployment.md`: the plan, the owner's steps, every environment variable.
2. `backend/Dockerfile`: the `dev`, `build` and `prod` stages; notice the non-root user
   and the health check.
3. `frontend/Dockerfile` and `frontend/Caddyfile`: the Node build stage, then Caddy;
   notice which paths go to the API and the strict CSP for the app.
4. `docker-compose.prod.yml`: the `x-backend` block shared by API, worker, beat and
   migrate; `depends_on` with `service_healthy` / `service_completed_successfully`; only
   Caddy has `ports`.
5. `.env.prod.example`: what an operator fills in, and why `DEMO_MODE` defaults to false.
6. `.github/workflows/ci.yml`, job `compose-prod`: how the production stack is tested
   without a real server (plain HTTP on port 80, checks through Caddy).
7. `.github/workflows/deploy.yml`: build-and-push for two architectures, then the SSH
   deploy that only runs when its secrets exist.
8. `simulator/gatesense_sim/world.py`: the timeline of scheduled actions; how one visit is
   a chain of steps; why the approval timeout uses the wall clock.
9. `backend/app/services/demo.py` (`nightly_reset`) and `app/setup_society.py`.
10. `docs/adr/0014-deployment-architecture.md`: why one server.

## Decisions and the alternatives we rejected

- **One VM with Compose** instead of several free platforms: free tiers in 2026 don't
  allow an always-on Celery worker, and their monthly caps run out under a simulator.
- **Caddy** instead of Nginx + Certbot: automatic HTTPS in a few lines of config.
- **Caddy serves the frontend** instead of Vercel: one origin, one deploy, no CORS.
- **Images built in CI** instead of on the server: what runs is exactly what was tested,
  and a small VM doesn't spend minutes compiling.
- **Compose** instead of Kubernetes: one server doesn't need an orchestrator.
- **Simulator through the public API** instead of writing to the database: it exercises
  the real code paths (auth, rate limits, approvals) and can't corrupt data.
- **Demo mode off by default**: a reset button on a real society's server would be a
  disaster; the operator has to turn it on deliberately.

## Likely interview questions

1. **Why multi-stage Docker builds?** The final image keeps only what runs: no compilers,
   caches or dev dependencies. Smaller, faster to pull, fewer things to exploit.
2. **Why run containers as non-root?** Least privilege: if the app is compromised, the
   attacker can't change the image's files or install tools as root.
3. **How does HTTPS get set up?** Caddy proves to Let's Encrypt that it controls the
   domain (an HTTP challenge on port 80), gets a certificate and renews it automatically.
4. **How do you deploy without downtime worries?** Compose pulls the new images, runs the
   migration step first, then recreates containers; health checks gate the order. A bad
   release is rolled back by starting the previous commit's tag.
5. **What happens to database changes on deploy?** A one-shot `migrate` service runs
   `alembic upgrade head` before the API starts (`service_completed_successfully`).
6. **How are secrets handled?** Never in git or images. `.env.prod` on the server, GitHub
   encrypted secrets for CI; gitleaks scans every commit.
7. **Why arm64 images too?** Oracle's free VM is Arm; one multi-arch tag serves both.
8. **How is the production setup tested if there's no server yet?** A CI job starts the
   real production stack and checks it through Caddy: routes, headers, non-root users,
   worker health and simulator traffic.
9. **Why does the simulator go through the API?** It tests the real system end to end and
   respects the same rules as real cameras and users.
10. **What's the weakest point of this deployment?** One server is a single point of
    failure. For a real society: off-site backups, monitoring with alerts, and a second
    server or a managed database.

## Exercise

Start the production stack on your own machine with plain HTTP:

```bash
cp .env.prod.example .env.prod
# set SITE_ADDRESS=:80, PUBLIC_BASE_URL=http://localhost, POSTGRES_PASSWORD and
# JWT_SECRET_KEY (any random text), DEMO_MODE=true, COMPOSE_PROFILES=demo
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

Open http://localhost, sign in as the guard and watch the simulator's cars arrive. Then
answer: which containers have a published port, and why only that one? What user does the
`api` container run as (`docker compose ... exec api id`)?
