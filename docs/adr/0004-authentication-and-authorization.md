# ADR-0004: Authentication and authorization

- **Status:** Accepted (pending owner review in the Phase 1 PR)
- **Date:** 2026-11-21

## Context

Three kinds of people log in (admin, guard, resident) and cameras call the API without a
person present. The brief asks for JWT access + refresh tokens, bcrypt or Argon2 hashing,
role-based access control through FastAPI dependencies, and hashed device API keys.

## Decision

1. **Passwords: Argon2id** via `argon2-cffi` (the current OWASP first choice; bcrypt also
   truncates passwords at 72 bytes). For an unknown email we still run a full Argon2 check
   against a dummy hash, so response time doesn't reveal which emails exist, and the error
   message is the same for every failure.
2. **Access tokens: JWT, HS256, 15 minutes**, sent as `Authorization: Bearer …`. The
   algorithm is pinned when decoding (a token can't choose `none`), and the required claims
   are `sub`, `type`, `jti`, `exp`. A `type` claim stops a refresh token being used as an
   access token and vice versa.
3. **Refresh tokens: JWT, 7 days, stored by `jti` and single-use (rotation).** Refreshing
   revokes the old token and issues a new pair. If a revoked token is presented again, we
   assume it was stolen and revoke *every* session of that user (reuse detection).
   Logout revokes the refresh token.
4. **The user is loaded from the database on every request** (one primary-key lookup). A
   deactivated user is locked out immediately, not when their token expires.
5. **RBAC with typed dependencies.** `require_roles(...)` returns a dependency; routes ask
   for `AdminUser` or `StaffUser` (admin + guard). The check runs before the route body.
   Guards may *read* flats and vehicles (needed at the gate); all other Phase 1 management
   routes are admin-only. A test walks every route with every role.
6. **Device API keys:** `gsd_` + 32 random bytes, shown once at creation or rotation. Only
   the SHA-256 hash is stored. A fast hash is fine because the key has 256 bits of entropy;
   slow hashing exists to protect *guessable* secrets like passwords. Sent in the
   `X-Device-Key` header; the device and its gate must both be active.
7. **Login uses the OAuth2 password form** (`username` + `password`), so the **Authorize**
   button in `/docs` works out of the box.
8. **Society scoping:** every query filters by the caller's `society_id`, and a record from
   another society returns 404 (not 403), so its existence isn't confirmed.

## Alternatives considered

- **Sessions in a cookie + server-side session store.** Simpler revocation, but cookies
  need CSRF protection, and the Telegram bot and camera devices aren't browsers. Rejected.
- **Long-lived access tokens without refresh tokens.** A stolen token would work for days.
  Rejected.
- **bcrypt.** Fine, but Argon2id is the current recommendation and has no 72-byte limit.
- **passlib.** Unmaintained and noisy with recent bcrypt versions. We call `argon2-cffi`
  directly.
- **RS256 (public/private key) JWTs.** Useful when other services verify our tokens; we are
  the only verifier, so HS256 with a strong secret is enough.
- **Keeping the user's role inside the JWT and skipping the database lookup.** Faster, but a
  demoted or deactivated user would keep their power until the token expires. Rejected.

## Consequences

- One indexed lookup per authenticated request; acceptable at our scale (measured in Phase 7).
- `JWT_SECRET_KEY` must be set in production; the app refuses to start with the dev default.
- Rate limiting of the login endpoint is added in Phase 7.
