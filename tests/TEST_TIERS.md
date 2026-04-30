# Test Tiers

- `unit`: default marker for fast tests (sqlite/mocked). Executed on every PR.
- `integration`: tests that require Postgres/Redis or external systems.
- `e2e`: full-stack flows expected to run with docker-compose.

Current CI runs only `unit` tests by default.
