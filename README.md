# 🚀 TitanCode Technologies — Backend MVP

A production-ready, highly observable FastAPI backend for managing applications, wallets, and real-time notifications.

---

## 🏗️ Architecture & Tech Stack

- **Core**: FastAPI (Python 3.12+)
- **Database**: PostgreSQL with SQLAlchemy 2.0 (Async)
- **Migrations**: Alembic
- **Real-Time**: WebSockets (Pub/Sub with `ConnectionManager`)
- **Security**: JWT (OAuth2 Password Bearer) & RBAC (Role-Based Access Control)
- **Hardening**: 
  - **SlowAPI**: Rate limiting (127.0.0.1 protection)
  - **JSON Logging**: Structured logs for production log aggregators
  - **Middleware**: Request timing & audit logging

---

## ⚡ Quick Start (Docker)

The fastest way to get started is using Docker Compose:

1. **Clone & Configure**:
   ```bash
   cp .env.example .env
   # Edit .env with your secrets
   ```

   For local development, you can keep `ENVIRONMENT=development` and use bootstrap defaults.
   For non-dev environments, you **must** set:
   - `ENVIRONMENT=staging` (or `production`)
   - `FIRST_SUPERUSER_PASSWORD=<strong-unique-password>` (must not be the repo default)
   - `AUTO_SEED_DEFAULT_ADMIN=false` (recommended after initial bootstrap)

2. **Run Services**:
   ```bash
   docker-compose up -d --build
   ```
   *The API will be available at `http://localhost:8000`.*

3. **Explore Documentation**:
   - **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
   - **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 🔐 Authentication & Roles

In development/test environments, the system can bootstrap with a **CEO** account:
- **Email**: `admin@titancode.com`
- **Password**: `TitanCodeAdmin123!`

> ⚠️ In non-dev environments, the app now fails fast if `FIRST_SUPERUSER_PASSWORD`
> is left on the default value (`TitanCodeAdmin123!`).

### 🔒 Secure Bootstrap Workflow (Staging/Production)

1. Set secure environment variables before first start:
   ```bash
   ENVIRONMENT=production
   FIRST_SUPERUSER=admin@yourcompany.com
   FIRST_SUPERUSER_PASSWORD='<long-random-password>'
   AUTO_SEED_DEFAULT_ADMIN=true
   ```
2. Start the API once so the admin account is created.
3. Log in as the seeded admin and create a secondary break-glass/admin user.
4. Rotate `FIRST_SUPERUSER_PASSWORD` to a value not used for login (or remove it from runtime secret set).
5. Disable future auto-seeding:
   ```bash
   AUTO_SEED_DEFAULT_ADMIN=false
   ```

See `DEPLOYMENT.md` for environment-by-environment guidance.

### Roles:
- **CEO / Admin**: Full access to all endpoints (Wallets, Apps, User lists).
- **Manager**: Can approve applications and view member profiles.
- **Member**: Access to their own wallet, applications, and profile.

---

## 📡 Real-Time Notifications (WebSockets)

TitanCode uses WebSockets for instant updates.

**Endpoint**: `ws://localhost:8000/api/v1/notifications/ws/{user_id}`

**Authentication**:
Since standard WebSocket headers are often limited by browsers, we use a query parameter:
`ws://.../ws/USER_ID?token=YOUR_JWT_ACCESS_TOKEN`

**Triggers**:
- Application Approved/Rejected.
- Wallet Credited/Debited.

---

## 📁 File Storage Engine

The system uses a pluggable `BaseStorage` interface.

- **Current Implementation**: `LocalStorage` (saves to `uploads/` directory).
- **Future Ready**: `S3Storage` placeholder included for AWS migration.
- **Storage Rules**:
  - Max Size: 10MB per file.
  - Allowed Formats: Configured via FastAPI File upload.
  - Organization: Sub-folders for `kyc/` and `portfolio/`.

---

## 🛡️ Production Hardening

### 1. Rate Limiting
- **Global**: 60 requests/minute per IP.
- **Auth**: Login (5/min) and Register (10/min) to prevent brute-force.

### 2. Structured Logging
Logs are printed in JSON format to `stdout`:
```json
{"message": "Rate limit exceeded", "request": "POST /api/v1/auth/login", "client_ip": "1.2.3.4", "status_code": 429}
```

### 3. Request Timing
Every response includes an `X-Process-Time` header (in milliseconds) and is logged with the precise execution duration.

---

## 🧪 Testing

We use `pytest` with an in-memory test engine:
```bash
# Inside venv
pytest tests/ -v
```
*Tests automatically bypass rate limiting via the `RATE_LIMIT_ENABLED` env var.*

---

## 📈 Roadmap
- [ ] Implement `S3Storage` class using `boto3`.
- [ ] Add Redis for distributed WebSocket Pub/Sub (currently in-memory).
- [ ] Integrate Sentry for error tracking.
