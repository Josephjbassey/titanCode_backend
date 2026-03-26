# TitanCode Technologies — Remaining MVP Items

This document tracks the features and integrations from `mvp_architecture.md` that are currently missing from the implementation.

## 1. Meetings Module
The entire meeting management and real-time communication system needs to be built.
- [ ] **Database Model**: Implement `Meeting` (id, title, type, link, scheduled_time, created_by, department_id, client_id).
- [ ] **API Endpoints**:
    - [ ] `POST /meetings/create`
    - [ ] `GET /meetings`
    - [ ] `GET /meetings/{id}`
    - [ ] `DELETE /meetings/cancel`
- [ ] **Real-time Integration**: Integrate **WebRTC** or **Agora** for live audio/video sessions.
- [ ] **Notifications**: Trigger WebSocket and Email alerts for meeting invites.

## 2. Revenue & Product Tracking
External product integration and financial reporting for the company.
- [ ] **Database Models**: 
    - [ ] `Product` (product_name, type, api_key, revenue_endpoint, product_url, created_by).
    - [ ] `Revenue` (product_id, amount, source, date).
- [ ] **API Endpoints**:
    - [ ] `POST /revenue/report` (External API for products to report earnings).
    - [ ] `GET /revenue/stats` (Admin dashboard data).
    - [ ] `POST /products/add`, `GET /products`, etc.
- [ ] **Wallet Sync**: Logic to automatically update the company wallet when revenue is reported.

## 3. Infrastructure & External Integrations
Moving from development placeholders to production-ready services.
- [ ] **Email Service**: Implement a core utility (SendGrid or SMTP) for:
    - [ ] Application approvals/rejections.
    - [ ] Meeting invites.
    - [ ] Payment/Withdrawal confirmations.
- [ ] **Background Jobs**: 
    - [ ] Configure **Celery + Redis** for async tasks.
    - [ ] Update `docker-compose.yml` with Redis and Celery worker/beat services.
- [ ] **Cloud Storage**: Implement the `S3Storage` backend in `app/core/storage.py` using `boto3`.

## 4. Financial & Client Refinements
- [ ] **Company Wallet**: Create a global/admin-level entity to track total company funds (currently only per-user wallets exist).
- [ ] **Withdrawals**: Implement a dedicated `withdrawals` table and status workflow (pending → approved → paid).
- [ ] **Client Project Requests**: Implement the `/client/request-project` endpoint for external clients.

---

*Last Updated: 2026-03-26*
