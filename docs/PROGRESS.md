# GateSense progress tracker

The build is split into phases (see `CLAUDE.md` §6). Each phase is one branch and one PR.
The agent updates this file at the start and end of every session.

| Phase | Name | Status | PR |
|---|---|---|---|
| 0 | Repo foundation | 🟡 In review | [#1](https://github.com/Akinchan-Jain-7/GateSense/pull/1) |
| 1 | Backend core, database, auth | ⚪ Not started | |
| 2 | Gate event engine | ⚪ Not started | |
| 3 | ANPR ML pipeline | ⚪ Not started | |
| 4 | Visitors, approvals, guest passes, real time | ⚪ Not started | |
| 5 | Escalation, notifications, scheduled jobs | ⚪ Not started | |
| 6 | Frontend (professional UI) | ⚪ Not started | |
| 7 | Hardening, offline mode, performance | ⚪ Not started | |
| 8 | Docker and deployment | ⚪ Not started | |
| 9 | Polish, docs, release | ⚪ Not started | |

**Next up:** Phase 1, once the owner merges PR #1.

## Standing rules from the owner

- Commits are authored by **Akinchan Jain**
  (`187171836+Akinchan-Jain-7@users.noreply.github.com`). Do **not** add Claude as an author
  or co-author, and add no "Generated with" footers to commits or PRs.

## Phase 0: Repo foundation

Branch: `phase-0-repo-foundation`

- [x] Monorepo skeleton (§4 layout), MIT licence, `.gitignore`, `.editorconfig`, `.gitattributes`
- [x] `.env.example` with every variable documented
- [x] Pre-commit: ruff, ruff-format, mypy, prettier, eslint, end-of-file, large files, gitleaks
- [x] Placeholder backend: FastAPI `/health`, uv, strict mypy, pytest
- [x] Placeholder frontend: Vite + React + strict TypeScript, ESLint, Prettier, Vitest
- [x] `docker-compose.yml`: Postgres, Redis, Mailpit, S3-compatible storage, backend, frontend
- [x] CI: backend + frontend lint/test, compose smoke test, gitleaks
- [x] README skeleton, `CONTRIBUTING.md` (Conventional Commits), PR + issue templates
- [x] ADR-0001 (monorepo and tech stack), ADR-0002 (dev object storage, **proposed**)
- [x] `docs/learn/phase-0.md`
- [x] Verified: CI green, including `docker compose up` on a GitHub runner

### Notes and deviations from the brief

- **MinIO → RustFS (proposed, needs owner OK).** MinIO stopped publishing official Docker
  images in October 2025, and the community edition is archived. RustFS is a drop-in
  S3-compatible replacement. See [ADR-0002](adr/0002-dev-object-storage.md).
- **TypeScript 6.0, not 7.0.** TypeScript 7 (the native Go compiler) is out, but
  `typescript-eslint` does not support it yet. See ADR-0001.
- **`httpx2` instead of `httpx`.** Starlette's test client now asks for `httpx2` and warns
  about `httpx`. Same API.
- **uv** manages the Python packages (lockfile, fast installs). See ADR-0001.
- **Created in later phases, not as empty placeholders:** `anpr/Dockerfile` (Phase 3),
  `docker-compose.prod.yml` and `.github/workflows/deploy.yml` (Phase 8). The folders for
  every part of §4 already exist with a README explaining what goes there.
- **Docker images couldn't be pulled in the agent's own workspace** (registries blocked), so
  `docker compose up` was verified by the `compose` CI job on GitHub's runners instead.
