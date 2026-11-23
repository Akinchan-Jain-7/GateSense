# Deployment

GateSense runs as one Docker Compose stack on one server: PostgreSQL, Redis, the API,
the Celery worker and beat, Mailpit, and Caddy in front, which gets the HTTPS certificate
and serves the web app. The ANPR worker runs next to the cameras (edge), not in the cloud.
The live demo adds the traffic simulator.

```
Internet ──443──▶ Caddy (web) ──▶ /api, /visit, /docs ──▶ API ──▶ PostgreSQL, Redis
                      │                                     ▲
                      └── static React app                  │ Celery worker + beat
Gate PC (ANPR worker) ──HTTPS + camera key──────────────────┘
Simulator (demo only) ──private network─────────────────────┘
```

The choice of host is the owner's decision; this page is the proposal (ADR-0014, status
_Proposed_) and the exact steps for either plan.

## Why one server, not several free platforms

The brief suggested Render / Railway / Fly.io for the API and workers, Vercel for the
frontend, Neon or Supabase for PostgreSQL and Upstash for Redis. Checked in November 2026
(verify the current terms before signing up; free tiers change often):

| Need                                      | Why the usual free tiers don't fit                                                                                                                                     |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Celery worker + beat running all the time | Render's free plan has no background workers, and free web services sleep after 15 minutes idle, which would also stop the escalation ladder and the approval timeouts |
| Redis that Celery polls constantly        | Upstash's free Redis is capped per month in commands; an idle Celery worker and beat use that up in days                                                               |
| PostgreSQL with steady load               | Neon's free plan is capped in compute hours per month; the simulator keeps it busy around the clock                                                                    |
| One origin for app, API and WebSocket     | Splitting frontend (Vercel) and API (another host) means CORS, two deploys and two URLs                                                                                |

One small VM runs everything above for free (Plan A) or for a few euros a month (Plan B),
and it is the same `docker-compose.prod.yml` anyone can use to self-host.

## Plan A: Oracle Cloud Always Free (Arm VM), free

Oracle's Always Free tier includes an Ampere (Arm) VM; as of 2026 the free allowance is
2 OCPUs and 12 GB of memory. CI publishes arm64 images, so nothing has to be built on the
server. The catch: free Arm capacity is often unavailable in popular regions, and Oracle
may reclaim idle free VMs. If creating the VM fails with "out of capacity", try another
availability domain, try again later, or use Plan B.

## Plan B: a small paid VPS

Any VPS with **2 vCPUs, 4 GB RAM, 40 GB disk**, Ubuntu 24.04, amd64 or arm64. Typical
prices are a few euros or dollars a month; check current prices. Everything below is the
same except step 2.

## What the owner does (step by step)

You create every account and type every secret yourself. Never paste secrets into a chat:
they go into the server's `.env.prod` file and into GitHub's secret settings.

**1. Pick a host.** Plan A (Oracle, free) or Plan B (VPS).

**2. Create the server.**

- _Oracle:_ sign up at oracle.com/cloud/free → Compute → Instances → Create instance →
  Image: Ubuntu 24.04 (aarch64) → Shape: Ampere `VM.Standard.A1.Flex`, 2 OCPU, 12 GB →
  add your SSH public key → Create. Then in the instance's subnet → Security List → add
  ingress rules for TCP 80 and 443 from `0.0.0.0/0`. Oracle's Ubuntu image also blocks
  those ports in its own firewall; on the server run:
  ```bash
  sudo iptables -I INPUT 6 -p tcp -m multiport --dports 80,443 -j ACCEPT
  sudo netfilter-persistent save
  ```
- _VPS:_ create an Ubuntu 24.04 server with your SSH key; open ports 22, 80 and 443.

**Shortcut for Plan A (or any fresh Ubuntu server):** steps 3 to 6 are automated by
[`scripts/oracle-cloud-init.sh`](../scripts/oracle-cloud-init.sh). On Oracle, paste the
whole file into *Create instance → Show advanced options → Management → Initialization
script* before creating the VM; elsewhere, run it once with `sudo bash`. It opens ports
80/443 in the server's firewall, installs Docker, clones the repo, writes `.env.prod` with
fresh random secrets (generated on the server, never shown anywhere), starts the demo
(`DEMO_MODE=true` with the simulator) at `https://<ip-with-dashes>.sslip.io`, and adds a
cron job that pulls new commits and images every 15 minutes, so step 8 is optional. You
still make the images public (step 5) and add the Security List rules (step 2). Follow
progress with `sudo tail -f /var/log/gatesense-setup.log`.

**3. Install Docker** (on the server):

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && exit   # log in again so the group applies
```

**4. Get the code and the settings file:**

```bash
git clone https://github.com/Akinchan-Jain-7/GateSense.git ~/gatesense
cd ~/gatesense
cp .env.prod.example .env.prod
nano .env.prod
```

Fill in the REQUIRED values:

- `SITE_ADDRESS`: your domain, or with no domain use your server's IP with dashes plus
  `.sslip.io`, e.g. `203-0-113-7.sslip.io` (a free DNS name that points at that IP).
- `PUBLIC_BASE_URL`: the same with `https://` in front.
- `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`: run `openssl rand -hex 32` on the server for each.
- For the live demo: `DEMO_MODE=true`, `COMPOSE_PROFILES=demo`. For a real society keep
  `DEMO_MODE=false` (with demo mode on, anyone could reset the data).

**5. Make the images public (once).** After the first merge to `main`, CI publishes
`gatesense-backend`, `-frontend`, `-simulator` and `-anpr` to GitHub Packages. New packages
start private: on GitHub → your profile → Packages → each package → Package settings →
Change visibility → Public. (Or keep them private and run
`docker login ghcr.io -u Akinchan-Jain-7` on the server with a token that has
`read:packages`.)

**6. Start it:**

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
```

The first start applies the database migrations (and, in demo mode, loads the demo
society). Open `https://<SITE_ADDRESS>`: Caddy gets the certificate within a minute.

**7. A real society only:** create the society and its first admin:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm -it api \
  python -m app.setup_society --society "Your Society" --admin-name "Your Name" \
  --admin-email you@example.org
```

It asks for the password. Everything else is added in the web app.

**8. Automatic deploys (optional).** So every merge to `main` updates the server:

1. On your own computer: `ssh-keygen -t ed25519 -f gatesense-deploy -N ""`.
2. On the server, add the contents of `gatesense-deploy.pub` to `~/.ssh/authorized_keys`.
3. On your computer: `ssh-keyscan -t ed25519 <server-address>` and copy the output.
4. On GitHub → the repo → Settings → Secrets and variables → Actions:
   - Secrets: `DEPLOY_HOST` (server address), `DEPLOY_USER` (e.g. `ubuntu`),
     `DEPLOY_SSH_KEY` (the whole contents of the private file `gatesense-deploy`),
     `DEPLOY_KNOWN_HOSTS` (the `ssh-keyscan` output).
   - Variables: `DEPLOY_URL` = `https://<SITE_ADDRESS>`.
5. Delete the private key file from your computer once it is saved in GitHub.

**9. Telegram (optional):** see [telegram.md](telegram.md); put the token and secret in
`.env.prod` and restart.

## Environment variables (`.env.prod`)

| Variable                    | Required | Meaning                                                                       |
| --------------------------- | -------- | ----------------------------------------------------------------------------- |
| `SITE_ADDRESS`              | yes      | Public hostname; Caddy gets its HTTPS certificate. `:80` = plain HTTP (tests) |
| `PUBLIC_BASE_URL`           | yes      | `https://` + the hostname; used in links inside emails                        |
| `POSTGRES_PASSWORD`         | yes      | Database password (random)                                                    |
| `JWT_SECRET_KEY`            | yes      | Signs login tokens (random); changing it signs everyone out                   |
| `IMAGE_PREFIX`, `IMAGE_TAG` | no       | Which images to run (default: GHCR, `latest`)                                 |
| `DEMO_MODE`                 | no       | `true` only for the public demo                                               |
| `DEMO_PASSWORD`             | no       | Password of the demo accounts                                                 |
| `COMPOSE_PROFILES`          | no       | `demo` also starts the traffic simulator                                      |
| `SIM_SPEED`                 | no       | Simulator time compression (keep `1` for the live demo)                       |
| `WEB_CONCURRENCY`           | no       | API processes; about the cores left after PostgreSQL (see performance.md)     |
| `METRICS_TOKEN`             | no       | If set, `/metrics` needs `Authorization: Bearer <token>`                      |
| `VISITOR_RETENTION_DAYS`    | no       | Visitor personal data is deleted after this many days (90)                    |
| `SMTP_*`                    | no       | Real email provider; empty = Mailpit catches all email                        |
| `TELEGRAM_*`                | no       | Telegram bot (see telegram.md)                                                |
| `SNAPSHOT_STORAGE`, `S3_*`  | no       | `local` volume (default) or an S3-compatible bucket                           |
| `LOG_LEVEL`                 | no       | `INFO`                                                                        |

GitHub Actions secrets for automatic deploys: `DEPLOY_HOST`, `DEPLOY_USER`,
`DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`; variable `DEPLOY_URL`. Nothing else: images are
pushed with the built-in `GITHUB_TOKEN`.

## Running it

```bash
cd ~/gatesense
alias gs='docker compose -f docker-compose.prod.yml --env-file .env.prod'
gs ps                       # health of every service
gs logs -f api worker       # follow logs
gs pull && gs up -d         # update by hand (CI does this when deploy secrets exist)
IMAGE_TAG=<older commit sha> gs up -d   # roll back to an earlier build
```

- **Email in demo mode** goes to Mailpit, reachable only from the server. To read it:
  `ssh -L 8025:127.0.0.1:8025 <user>@<server>` and open `http://localhost:8025`.
- **Backups:** `gs exec -T postgres pg_dump -U gatesense gatesense | gzip > backup-$(date +%F).sql.gz`
  (put it in a daily cron job and copy the files off the server).
- **Metrics:** Prometheus can scrape `http://api:8000/metrics` on the private network; to
  look by hand: `gs exec api python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8000/metrics').read().decode())"`.
  Caddy hides `/metrics` from the internet.
- **The demo resets itself** every night at 04:00 IST (only when `DEMO_MODE=true`); the
  simulator notices and starts over.

## The ANPR worker at the gate

The camera side runs on a PC at the gate, not on the server: see [anpr/README.md](../anpr/README.md).
Point it at the server and give it a camera key (Admin → Gates → Rotate camera key):

```bash
ANPR_API_URL=https://<SITE_ADDRESS> ANPR_DEVICE_KEY=<key> uv run gatesense-anpr --source rtsp://...
```

If the internet drops, it buffers reads on disk and sends them in order when it's back.

## How the pieces were tested

- CI job **Production stack** builds the production images, starts the whole stack in
  demo mode with plain HTTP, and checks through Caddy: the app and its routes, the CSP
  header, `/metrics` hidden, the API port not published, every container running as a
  non-root user, the worker answering, and the simulator producing gate events.
- The **Deploy** workflow builds amd64 + arm64 images on every green `main` and, once the
  deploy secrets exist, updates the server over SSH and checks `/health` and `/ready`.
- Not yet tested: a real server with a real certificate. That waits on step 1.
