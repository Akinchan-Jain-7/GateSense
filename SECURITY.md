# Security

## Reporting a problem

Please don't open a public issue for a security problem. Use GitHub's private reporting
instead: the repository's **Security** tab → **Report a vulnerability**. If that button
isn't there, open an issue that only asks for a private contact, without details.

You'll get a reply within a week. This is a portfolio project run by one person, so there
is no bounty, but every report is fixed or answered, and credited if you like.

## What's in place

| Area | How |
|---|---|
| Sign-in | JWT access tokens (short-lived) with rotating refresh tokens; passwords hashed with Argon2 ([ADR-0004](docs/adr/0004-authentication-and-authorization.md)) |
| Permissions | Role checks (admin, guard, resident) on every route, tested route by route; residents only see their own flats |
| Cameras | Per-device API keys, stored hashed, shown once, rotatable; the laptop webcam preview listens on 127.0.0.1 only |
| Abuse | Rate limits on sign-in and camera endpoints; request size limits; security headers and a strict CORS list ([ADR-0013](docs/adr/0013-hardening-and-observability.md)) |
| Secrets | Only `.env.example` is committed; gitleaks scans every pull request |
| Privacy | Phone numbers masked in lists; visitor personal data and snapshots deleted after 90 days (configurable); admin actions audited |
| Guest pass codes | One-time codes stored hashed, with a time window and a usage limit |

Known limits are listed in the [README](README.md#known-limitations).
