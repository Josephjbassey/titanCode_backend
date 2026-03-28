TitanCode "Iron-Clad" Backend Architecture Prompt
Role: You are a Senior Staff Backend Engineer and Security Architect. You are building the core financial and operational engine for a high-growth tech agency. Your code must be modular, "military-grade" secure, and ready for high-concurrency production environments.

The Mission: Implement the Event-Driven Payout & Financial Ledger System. The system must handle project completion, calculate multi-member profit splits, update virtual wallets, and prepare admin-approved payouts without blocking the main API thread.

Tech Stack (Immutable):

Framework: FastAPI (Asynchronous)

Task Queue: Celery + Redis (Message Broker)

Database: PostgreSQL (using asyncpg and SQLAlchemy 2.0)

Deployment: Docker & Docker Compose (Production-ready)

Security: SlowAPI (Rate Limiting), PyJWT (Auth), Passlib (Argon2/Bcrypt)

1. Architectural & Security Constraints (Hard Rules)
Financial Integrity: Use Decimal or Numeric(10, 2) for all currency fields. NEVER use floats. 2. Idempotency: The Payout task must be idempotent. If triggered twice for the same project_id, it must check for an existing PayoutInvoice and abort to prevent double-funding.

Security (OWASP Top 10): * Implement strict BOLA/IDOR protection: Ensure users can only view their own wallets/transactions.

Implement Rate Limiting on the /auth/login and /payout/approve endpoints using SlowAPI.

Use Atomic Transactions: Payout logic must be wrapped in async with session.begin(): to ensure "all-or-nothing" database consistency.

Performance: The login endpoint must use run_in_threadpool or a standard def to avoid blocking the FastAPI event loop during heavy CPU-bound password hashing.

2. Database Schema (SQLAlchemy 2.0)
Wallet: user_id (FK), balance, currency.

Transaction: id, wallet_id (FK), amount, type (CREDIT/DEBIT), reference_id (Project ID), description, timestamp.

Project: id, title, total_budget, status (DRAFT/ACTIVE/COMPLETED), assigned_members (M2M).

PayoutInvoice: id, project_id (FK), total_payout_amount, is_approved (Boolean, default False), processed_at.

3. The Implementation Flow
A. The Trigger (FastAPI Router)
Endpoint: PUT /api/v1/projects/{project_id}/status

Action: Update status to COMPLETED.

Handoff: Immediately dispatch a Celery task: process_payout_calculation.delay(project_id). Return a 202 Accepted response to the frontend.

B. The Background Worker (Celery Task)
Task: process_payout_calculation

Logic: 1. Fetch Project and assigned Team Members.
2. Calculate the split (Assume 70% to team, 30% to company operations for now).
3. Update the Wallet balance for every assigned member.
4. Log each movement in the Transaction table.
5. Generate a PayoutInvoice flagged as is_approved=False.
6. Logging: Use structured JSON logging for every step of the money movement.

C. The Admin Guard (FastAPI Router)
Endpoint: POST /api/v1/admin/payouts/{invoice_id}/approve

Action: Verify the Admin role, then flip the is_approved bit. This is the "Safety Net" before Phase 2 (the actual Bank Transfer API).

4. DevOps & Production Readiness
Provide a Dockerfile using a multi-stage build (slim image).

Provide a docker-compose.yml that spins up: api, db, redis, and celery_worker.

Configure Gunicorn with Uvicorn workers for the production entry point.

Ensure all environment variables (DB URLs, Secret Keys) are handled via a .env pattern.

Output: Provide the implementation in a clean, professional directory structure. Focus on the core logic in tasks.py, models.py, and routers/financials.py.