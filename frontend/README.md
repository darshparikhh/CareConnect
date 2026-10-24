# CareConnect Frontend

React + Vite + TypeScript SPA for CareConnect. Hosts three role-scoped
dashboards (patient, volunteer, clinician) behind a sign-in screen and talks to
the FastAPI backend.

## Setup

```bash
npm install
```

Copy `.env.example` to `.env` to point at a non-default backend:

```bash
cp .env.example .env
# VITE_API_BASE_URL defaults to http://localhost:8000 when unset
```

## Scripts

- `npm run dev` — start the dev server on http://localhost:5173 (allow-listed by the backend's CORS).
- `npm run build` — type-check and build for production.
- `npm run typecheck` — type-check only (`tsc --noEmit`).
- `npm run preview` — preview the production build.

## Structure

```
src/
  api/         typed HTTP client + shared API types
  auth/        session storage, auth context/provider, route guards
  components/  shared UI (dashboard shell, sign-out)
  pages/       sign-in screen + role dashboard placeholders
  App.tsx      route table (role-scoped routes)
  main.tsx     entry point
```

Dashboard content (tasks 19-21) builds into `src/pages` and `src/components`.
