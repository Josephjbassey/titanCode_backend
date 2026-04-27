# Deployment Guide

This document covers secure environment setup for staging and production.

## 1) Required security settings

Set these values through your secret manager (not committed files):

```bash
ENVIRONMENT=production
SECRET_KEY=<32+ byte random secret>
DATABASE_URL=<production database url>
FIRST_SUPERUSER=<admin email>
FIRST_SUPERUSER_PASSWORD=<strong unique bootstrap password>
AUTO_SEED_DEFAULT_ADMIN=true
```

### Fail-fast behavior

On startup, the app validates bootstrap credentials.

If `ENVIRONMENT` is not a dev/test value and `FIRST_SUPERUSER_PASSWORD` is still the default (`TitanCodeAdmin123!`), startup exits immediately with a configuration error.

## 2) One-time bootstrap

1. Deploy with `AUTO_SEED_DEFAULT_ADMIN=true`.
2. Confirm startup logs indicate default admin creation or existing admin.
3. Log in and create additional privileged users as needed.
4. Disable further seeding by setting:

```bash
AUTO_SEED_DEFAULT_ADMIN=false
```

Redeploy after this change.

## 3) Recommended environment matrix

- Development/Test:
  - `ENVIRONMENT=development` (or `test`)
  - `AUTO_SEED_DEFAULT_ADMIN=true` (optional)
  - Default bootstrap password allowed only here.
- Staging/Production:
  - `ENVIRONMENT=staging` or `production`
  - `FIRST_SUPERUSER_PASSWORD` must be non-default
  - `AUTO_SEED_DEFAULT_ADMIN=false` after initial bootstrap

## 4) Post-bootstrap hardening checklist

- Rotate bootstrap password in your secret manager.
- Keep `AUTO_SEED_DEFAULT_ADMIN=false` for normal operations.
- Restrict access to deployment secrets.
- Audit privileged users periodically.
