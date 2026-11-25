# Contributing

Follow the [README installation steps](README.md#what-to-install-first) to install the required
tools. The project uses Python 3.12 and Node.js 24. From the project folder, install dependencies:

```sh
uv sync --locked --all-extras
npm --prefix apps/web ci
```

## Checks

With Docker running, run `make check` from the project folder. It automatically starts the
isolated disposable test database and waits until it is ready before running database tests.
`make test` and `make coverage` also start the test database automatically. Your application
database is unaffected.

`make coverage` checks code coverage, including branches, and requires at least 90%. To run only
the frontend tests, run `npm test` from `apps/web`.

### Browser tests

Stop your normal API and frontend with Ctrl+C first. Browser tests start their own API and frontend
on the same ports (`8780` and `5273`). Keep Docker running, then run these commands from the
project folder:

```sh
make db-test-up
cd apps/web
npx playwright install chromium
npm run test:e2e
```

Browser tests reset the disposable test database before starting. Your application database is
unaffected.

Tests must never target a user's application database. `scripts/run_tests.py` and database fixtures
validate the disposable database identity before migrations or cleanup. The default test service
uses port 57433 and database `review_oss_test`; development uses port 57432 and `review_oss`.
Do not run database suites and browser end-to-end tests concurrently against the test service.

## Test organization

- Unit tests check algorithms, validation and rendering. Most run without a database; a few use
  the disposable test database.
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
