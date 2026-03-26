# Backend MVP Architecture: TitanCode Technologies

## 1. Backend Technology Stack
Recommended stack based on scalability and a focus on Python.

* **Language:** Python
* **Framework:** FastAPI (high-performance APIs)
* **ORM:** SQLAlchemy
* **Authentication:** JWT
* **Database:** PostgreSQL
* **Caching:** Redis
* **File Storage:** AWS S3 / Cloudinary
* **Email Service:** SendGrid / SMTP
* **Background Jobs:** Celery + Redis
* **WebSocket Server:** Socket.IO or FastAPI WebSockets

---

## 2. System Architecture
Basic system structure and data flow.

```text
       Frontend (React / Next.js)
                 |
                 |
            API Gateway
                 |
          FastAPI Backend
                 |
 ---------------------------------
 |               |               |
Auth         Core API        WebSockets
Service      Services        (meetings)
 |               |               |
 ---------------------------------
                 |
        PostgreSQL Database
                 |
            Redis Cache
                 |
      External Integrations
    (payment, apps, revenue)
```

---

## 3. Authentication System
Authentication will use JSON Web Tokens (JWT).

### Login Flow
1. User logs in.
2. Backend verifies credentials.
3. Server returns Access Token (JWT) and Refresh Token.

**Token Example:**
```json
{
  "user_id": 104,
  "role": "manager",
  "department": "frontend",
  "exp": 1678901234
}
```

### Security Measures
* **Password Hashing:** `bcrypt`
* **Token Expiration:** 15 minutes
* **Refresh Token:** 7 days

---

## 4. User Roles (Permission System)
The backend must enforce Role-Based Access Control (RBAC).

| Role | Example Permissions |
| :--- | :--- |
| **CEO** | Full control |
| **Admin** | Manage departments |
| **Manager** | Manage department |
| **Assistant** | Help manager |
| **Member** | Work on projects |
| **Applicant** | Waiting approval |
| **Client** | Create projects |

---

## 5. Database Schema

### `users`
* **Fields:** `id`, `full_name`, `email`, `password_hash`, `country`, `phone_number`, `github_url`, `portfolio_url`, `role`, `department_id`, `experience_years`, `skills`, `tools`, `bank_name`, `bank_account_number`, `status`, `created_at`
* **Status:** `pending`, `approved`, `rejected`

### `departments`
* **Fields:** `id`, `name`, `description`, `manager_id`, `assistant_id`, `created_at`
* **Example Departments:** Frontend, Backend, Full Stack, Game Development, UI/UX, Cybersecurity, Data Science, Content Creation, Mobile Development.

### `applications`
* **Fields:** `id`, `user_id`, `department_id`, `github_url`, `portfolio`, `status`, `reviewed_by`, `reviewed_at`
* **Status:** `pending`, `approved`, `rejected`

### `projects`
* **Fields:** `id`, `name`, `description`, `client_id`, `budget`, `deadline`, `status`, `created_at`
* **Status:** `pending`, `active`, `completed`, `cancelled`

### `tasks`
* **Fields:** `id`, `project_id`, `assigned_user`, `task_title`, `description`, `status`, `deadline`, `created_at`
* **Status:** `open`, `in_progress`, `completed`

### `meetings`
* **Fields:** `id`, `title`, `meeting_type`, `meeting_link`, `created_by`, `department_id`, `client_id`, `scheduled_time`
* **Types:** `audio`, `video`

### `revenue`
Tracks income from products.
* **Fields:** `id`, `product_id`, `amount`, `source`, `date`
* **Source Examples:** `website`, `mobile_app`, `game`, `subscription`

### `products`
Tracks company apps/websites.
* **Fields:** `id`, `product_name`, `product_type`, `api_key`, `revenue_endpoint`, `product_url`, `created_by`
* **Types:** `website`, `mobile_app`, `game`, `platform`

### `payments`
Tracks payments to members.
* **Fields:** `id`, `user_id`, `project_id`, `amount`, `status`, `payment_date`
* **Status:** `pending`, `paid`

### `company_wallet`
Tracks company funds.
* **Fields:** `id`, `total_balance`, `last_updated`

### `withdrawals`
* **Fields:** `id`, `requested_by`, `amount`, `bank_name`, `bank_account`, `status`, `created_at`

---

## 6. API Structure
**Base URL:** `/api/v1/`

### Authentication APIs
* `POST /auth/register`
* `POST /auth/login`
* `POST /auth/logout`
* `POST /auth/refresh`
* `GET /auth/profile`

### User APIs *(Admin only)*
* `GET /users`
* `GET /users/{id}`
* `PUT /users/update`
* `DELETE /users/{id}`

### Application APIs *(Managers approve applicants)*
* `POST /applications/apply`
* `GET /applications`
* `PUT /applications/approve`
* `PUT /applications/reject`

### Department APIs
* `GET /departments`
* `POST /departments/create`
* `PUT /departments/update`
* `DELETE /departments/delete`

### Project APIs
* `POST /projects/create`
* `GET /projects`
* `GET /projects/{id}`
* `PUT /projects/update`
* `DELETE /projects/delete`

### Task APIs
* `POST /tasks/create`
* `GET /tasks`
* `PUT /tasks/update`
* `PUT /tasks/complete`

### Meeting APIs
* `POST /meetings/create`
* `GET /meetings`
* `GET /meetings/{id}`
* `DELETE /meetings/cancel`

### Revenue APIs
Used to track revenue from external apps sending revenue data.
* `POST /revenue/report`
* `GET /revenue/stats`
* `GET /revenue/product/{id}`

**Example Request:**
```json
// POST /revenue/report
{
 "product_id": 4,
 "amount": 1200
}
```

### Product Integration APIs *(CEO adds product)*
* `POST /products/add`
* `GET /products`
* `PUT /products/update`
* `DELETE /products/remove`

### Payment APIs
* `POST /payments/send`
* `GET /payments/history`
* `GET /payments/user/{id}`

### Company Wallet APIs *(CEO/Admin only)*
* `GET /wallet/balance`
* `POST /wallet/withdraw`
* `GET /wallet/transactions`

### Client APIs
* `POST /client/request-project`
* `GET /client/projects`

---

## 7. Integrations & Systems

### Meeting Integration
Use **WebRTC** or **Agora**.
1. CEO schedules meeting.
2. Backend generates meeting link.
3. Sends notifications.
4. Participants join meeting.

### Notification System
Use **WebSockets** for real-time events:
* `new_project`
* `meeting_invite`
* `task_assigned`
* `payment_sent`
* `application_approved`

### Email System
Backend sends email for:
* Application approval
* Meeting invite
* Payment confirmation
* Project updates

### File Upload System
Storage via **AWS S3** or **Cloudinary**.
* Portfolio files
* Project files
* Profile images

---

## 8. Security Measures
Important protections to implement:
* JWT authentication
* Rate limiting
* SQL injection protection
* Password hashing (`bcrypt`)
* Role-based permissions
* CORS protection
* HTTPS

---

## 9. Admin Default Login
Generated when the database is first created. The user must change the password after the first login.

* **Email:** `admin@titancode.com`
* **Password:** `TitanCodeAdmin123!`
* **Role:** `CEO`

---

## 10. Revenue Integration Example
Example integration for a mobile app adding to the company wallet:

**Request:**
`POST https://titancode.com/api/v1/revenue/report`

**Body:**
```json
{
 "product_id": 3,
 "amount": 250
}
```

---

## 11. Deployment Architecture
Recommended hosting providers:

* **Backend:** AWS EC2, DigitalOcean, Railway, Render
* **Database:** AWS RDS, Supabase, Neon PostgreSQL
* **Storage:** AWS S3, Cloudinary

---

## 12. MVP Features Summary
The Backend MVP includes:
* Authentication system
* Role-based permissions
* Department management
* Application approval system
* Project management
* Task assignment
* Meeting scheduling
* Revenue tracking
* Product integration
* Company wallet
* Payment system
* Client hiring system
* Notification system