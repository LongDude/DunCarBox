# Repository Guidelines

## Project Structure & Module Organization

The backend is a Python 3.12 FastAPI service under `backend/app`, with domain
models, API routes, PostgreSQL storage, and packing engines in separate
packages. Backend tests live in `backend/tests`, including focused packing
tests. The frontend is a React/TypeScript/Vite application under
`frontend/src`; browser tests are in `frontend/e2e` and unit tests sit beside
the modules they cover. `demo/` contains fixture data, `docs/` contains
architecture and operational notes, and `infra/` contains Docker/Kubernetes,
OpenTofu, and DDNS tooling. Root Compose files provide production-like and
containerized development stacks.

## Build, Test, and Development Commands

- `make dev-up` starts the local Docker development stack with Vite hot reload.
- `make dev-logs` and `make dev-down` inspect or stop that stack.
- `docker compose up --build` builds and runs the regular local stack.
- `cd backend && uv run pytest` runs backend tests; add `-m stress` only for
  expensive benchmarks.
- `cd frontend && npm test` runs Vitest; `npm run build` type-checks and builds.
- `cd frontend && npm run test:e2e` runs Playwright browser tests.
- `make test-ops` and `make test-ddns` run infrastructure script tests.

## Coding Style & Naming Conventions

Use four spaces in Python and two spaces in YAML. Python follows Ruff rules
(`backend/pyproject.toml`), with `snake_case` functions and variables and
`PascalCase` classes. TypeScript uses two spaces, semicolons, single quotes,
`camelCase` functions, and `PascalCase` React components. Keep tests named
`test_*.py`, `*.test.ts(x)`, or `*.spec.ts` according to their runner.

## Testing Guidelines

Add focused tests next to the changed module and preserve deterministic fixture
inputs in `demo/` or `frontend/src/features/demo/fixture-data/`. Run the
smallest relevant suite first, then the broader backend, frontend, or infra
suite before submitting. Stress tests are opt-in and should not run by default.

## Commit & Pull Request Guidelines

Recent commits are short imperative or descriptive subjects (for example,
`dev containers` or `Add big test`); keep commits focused and avoid mixing
unrelated infrastructure and product changes. Pull requests should explain
the behavior change, list validation commands, identify configuration or
migration impact, and include screenshots for visible frontend changes.

## Security & Configuration Tips

Keep `.env`, Cloudflare tokens, passwords, and generated OpenTofu state out of
commits. Use `.env.example` and `infra/ddns-client/config.conf.example` as
templates. Local services should remain bound to `127.0.0.1`; production
network and TLS changes belong in the documented `infra/` workflow.
