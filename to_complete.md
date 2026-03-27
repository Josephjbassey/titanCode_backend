# TitanCode Technologies — Remaining MVP Items

This document tracks the features and integrations from `mvp_architecture.md` that are currently missing from the implementation.

## 1. Meetings Module
The entire meeting management and real-time communication system has been built.
- [x] **Database Model**: Implement `Meeting` (id, title, type, link, scheduled_time, created_by, department_id, client_id).
- [x] **API Endpoints**: `POST /meetings/create`, `GET /meetings`, `GET /meetings/{id}`, `DELETE /meetings/cancel`, `GET /meetings/{id}/join`.
- [x] **Real-time Integration**: Integrate **WebRTC** or **Agora** for live audio/video sessions (Simulated link generation).
- [x] **Notifications**: Trigger WebSocket and Email alerts for meeting invites.

## 2. Revenue & Product Tracking
External product integration and financial reporting for the company.
- [x] **Database Models**: 
    - [x] `Product` (product_name, type, api_key, revenue_endpoint, product_url, created_by).
    - [x] `Revenue` (product_id, amount, source, date).
- [x] **API Endpoints**:
    - [x] `POST /revenue/report` (External API for products to report earnings).
    - [x] `GET /revenue/stats` (Admin dashboard data).
    - [x] `POST /products/add`, `GET /products`, etc.
- [x] **Wallet Sync**: Logic to automatically update the company wallet when revenue is reported.

## 3. Infrastructure & External Integrations
Moving from development placeholders to production-ready services.
- [x] **Email Service**: Implement a core utility (Mock implementation done).
    - [x] Application approvals/rejections (Handled in applications.py).
    - [x] Meeting invites (Handled in meetings.py).
    - [x] Payment/Withdrawal confirmations (Task created).
- [x] **Background Jobs**: 
    - [x] Configure **Celery + Redis** for async tasks.
    - [x] Update `docker-compose.yml` with Redis and Celery worker/beat services.
- [x] **Cloud Storage**: Implement the `S3Storage` backend in `app/core/storage.py` using `boto3`.

## 4. Financial & Client Refinements
- [x] **Company Wallet**: Create a global/admin-level entity to track total company funds.
- [x] **Withdrawals**: Implement a dedicated `withdrawals` table and status workflow (pending → approved → paid).
- [x] **Client Project Requests**: Implement the `/client/request-project` endpoint for external clients.

---

*Last Updated: 2026-03-26*
