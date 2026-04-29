# TitanCode Backend — Technical Debt Assessment

_Date: 2026-04-29_

## Highest-priority technical debt

1. **Business logic is concentrated in API endpoints (fat endpoint pattern).**
   - Evidence: existing senior review calls out logic in `projects.py` and `client.py` living inside route handlers.
   - Risk: harder unit testing, duplicated logic, slower onboarding, regression risk.

2. **Performance debt from N+1 query patterns.**
   - Evidence: project listing path previously identified as N+1 hotspot.
   - Risk: latency and DB load increase sharply as project/member counts grow.

3. **Webhook verification inconsistency (especially Flutterwave path).**
   - Evidence: review flags weaker static-hash validation model than per-request signatures.
   - Risk: elevated spoofing risk if secret leaks; weaker non-repudiation.

4. **Reliability gap in async financial workflows.**
   - Evidence: Celery failure/recovery strategy and DLQ/alerting concerns called out.
   - Risk: payout/revenue state drift, manual reconciliation burden.

5. **Security hardening not fully closed (bootstrap credentials/process risk).**
   - Evidence: default admin bootstrap pattern still documented in README.
   - Risk: misconfiguration in staging/prod can create critical account takeover exposure.

6. **Test execution depends on strict runtime env setup.**
   - Evidence: tests currently fail to start without required env vars (`SECRET_KEY`, `DATABASE_URL`).
   - Risk: inconsistent CI/local quality signal and slower development feedback loops.

7. **Roadmap-level observability debt (APM/Sentry not integrated).**
   - Evidence: roadmap tracks Sentry as pending.
   - Risk: longer incident detection/triage time, poorer MTTR in production.

## Remediation plan (practical sequence)

### Phase 1 (Week 1): Contain high-risk security/reliability issues
- Enforce webhook signatures uniformly (HMAC + timestamp + replay window) for all providers.
- Add Celery retry policies, dead-letter queue routing, and admin alerting on final failure.
- Lock bootstrap behavior further: disable default credentials in non-development profiles and add startup checks.

### Phase 2 (Week 2): Performance and architecture cleanup
- Refactor endpoint-heavy domains into service layer modules (`project_service`, `client_service`, `billing_service`).
- Audit list/read endpoints for eager loading (`selectinload`) and add query-count regression tests.
- Add pagination defaults and upper bounds where missing.

### Phase 3 (Week 3): Testing and delivery hardening
- Add `.env.test` + test bootstrap helper to guarantee required settings for `pytest`.
- Split test tiers: unit (fast, sqlite/mocked), integration (postgres/redis), e2e (docker-compose).
- Add CI pipeline gates: lint, type checks, unit tests, migration check.

### Phase 4 (Week 4): Observability and financial integrity controls
- Integrate Sentry/OpenTelemetry with request + job correlation IDs.
- Add invariants for wallet/accounting writes (every balance mutation must create a transaction record).
- Add daily reconciliation job + report for revenue, wallets, and payouts.

## Suggested ownership model
- **Backend lead:** service-layer refactor, query optimization.
- **Platform/DevOps:** CI, env management, observability stack.
- **Security owner:** webhook auth model, secret rotation policy.
- **Finance workflow owner:** reconciliation and payout consistency checks.

## Definition of done (measurable)
- 0 known N+1 hotspots in top 10 API endpoints (verified by tests/metrics).
- 100% webhook handlers use signed request validation + replay protection.
- Celery critical tasks have retry + DLQ + alert route.
- CI green on PRs with required checks.
- Incident visibility live in production (Sentry/APM dashboards).
