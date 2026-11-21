# GateSense frontend

React + TypeScript + Vite. Phase 0 is a placeholder page; the Guard, Resident and Admin
apps are built in Phase 6.

```bash
cd frontend
npm ci              # install exact versions from package-lock.json
npm run dev         # http://localhost:5173
npm test            # Vitest + React Testing Library
npm run lint        # ESLint (strict, type-aware)
npm run format:check
npm run typecheck
npm run build
```

Folder guide:

| Folder            | What lives there                                                    |
| ----------------- | ------------------------------------------------------------------- |
| `src/app/`        | App shell, routing, providers.                                      |
| `src/features/`   | One folder per feature (guard console, approvals, guest passes, …). |
| `src/components/` | Shared UI components (design system).                               |
| `src/lib/`        | API client, generated OpenAPI types, helpers.                       |
| `src/i18n/`       | English + Hindi translations.                                       |
| `tests/`          | Vitest component tests.                                             |
| `e2e/`            | Playwright end-to-end tests (Phase 6).                              |
