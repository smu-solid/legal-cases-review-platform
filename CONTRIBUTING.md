# Contributing

Use Python 3.12 and Node.js 24. Install locked dependencies with `uv sync --locked --all-extras`
and `npm ci` in `apps/web`.

## Checks

With Docker running, run `make check`. It starts the isolated disposable test database, waits
until it is ready, then runs the checks. `make test` and `make coverage` also start the test
database automatically. Your application database is unaffected.

`make coverage` enables branch coverage and enforces the 90% floor. Frontend tests run with
`npm test`; browser checks run with `npm run test:e2e` from `apps/web` after installing Playwright
Chromium with `npx playwright install chromium`.

Tests must never target a user's application database. `scripts/run_tests.py` and database fixtures
validate the disposable database identity before migrations or cleanup. The default test service
uses port 57433 and database `review_oss_test`; development uses port 57432 and `review_oss`.
Do not run database suites and browser end-to-end tests concurrently against the test service.

## Test organization

- Unit tests prove algorithms, validation and rendering without a database.
- API tests prove requests, authorization and response contracts.
- Integration/security tests prove persistence, isolation, concurrency and rollback.
- Shared builders live in `tests/support`, rather than being imported from test modules.
- Frontend component tests use controlled API scenarios. Real-backend browser tests exercise the
  complete application independently of those mocks.

Keep assertions about retained behavior when restructuring tests. Security, isolation, idempotency,
audit, locking and all-or-nothing allocation publication are part of the application contract.

## API changes

Regenerate the contract with `uv run python scripts/generate_openapi.py`, then run
`npm run openapi:generate` in `apps/web`. Include contract and generated-type changes together.
