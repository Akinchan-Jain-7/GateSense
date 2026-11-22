# Frontend image, two targets:
#   dev  (docker-compose.yml):      the Vite dev server with live reload
#   prod (docker-compose.prod.yml): the static build served by Caddy, which is also the
#                                    single public entry point: HTTPS (automatic
#                                    certificates), and /api, /visit and /docs forwarded to
#                                    the API container. See Caddyfile.
# The build runs on the CI machine's own CPU even when making an arm64 image: its output
# (HTML, JS, CSS) is the same for every platform, and emulating arm64 would be slow.
FROM --platform=$BUILDPLATFORM node:22-alpine AS base
WORKDIR /app
# Dependencies first so this layer is cached until package*.json changes.
COPY package.json package-lock.json ./
RUN npm ci


# --- Development ---------------------------------------------------------------------
FROM base AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]


# --- Production: build the static files ----------------------------------------------
FROM base AS build
COPY . .
# The API is on the same origin (Caddy forwards /api), so no API URL is baked in.
RUN npm run build


# --- Production: the image that runs -------------------------------------------------
FROM caddy:2-alpine AS prod

# The official image runs as root; give Caddy its own user instead. Its binary already has
# the capability to listen on ports 80 and 443 without root.
RUN addgroup -S caddy && adduser -S -G caddy -H -s /sbin/nologin caddy \
    && chown -R caddy:caddy /data /config

COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv

USER caddy
# /data holds the HTTPS certificates: mount a volume so they survive restarts (Let's
# Encrypt limits how often a certificate can be issued).
VOLUME ["/data", "/config"]
EXPOSE 80 443

# Caddy's admin endpoint answers on localhost only.
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:2019/config/"]
