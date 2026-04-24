# TitanCode Technologies: User & Onboarding Flows

This document outlines the end-to-end lifecycle for every role within the TitanCode platform, from initial registration to project completion and financial settlement.

---

## 1. Onboarding Flows (By Role)

### 👑 CEO (The Founder)
*   **Onboarding**: Bootstrapped automatically during system initialization.
*   **Credentials**: Default admin email/password.
*   **Key Action**: First task is to create the initial **Departments** (Frontend, Backend, etc.) and promote the first set of **Admins**.

### 🛠️ Admin (Operations)
*   **Onboarding**: Registers as a standard user.
*   **Promotion**: The CEO updates their role to `Admin` via `PUT /api/v1/users/update`.
*   **Responsibility**: Managing the global state, approving products, and overseeing financial withdrawals.

### 💼 Manager (Department Lead)
*   **Onboarding**: Registers as a standard user.
*   **Promotion**: CEO or Admin updates their role to `Manager` and assigns them as `manager_id` to a specific Department.
*   **Responsibility**: Reviewing applications, creating projects, and assigning tasks to Members.

### 💻 Member / Applicant (The Talent)
*   **Step 1: Registration**: User signs up via `POST /api/v1/auth/register`. They are assigned the `Member` role but start with `pending` status (essentially an **Applicant**).
*   **Step 2: Application**: The user browses departments and submits an application via `POST /api/v1/applications/apply`, providing their GitHub and Portfolio.
*   **Step 3: Review**: A Manager reviews the application.
*   **Step 4: Activation**: Upon approval (`PUT /api/v1/applications/approve`), the user's status becomes `approved`, and they are officially joined to the department.

### 🤝 Client (The Customer)
*   **Onboarding**: Registers as a standard user.
*   **Validation**: CEO or Admin verifies the client's identity/intent and updates their role to `Client`.
*   **Readiness**: Once assigned the `Client` role, they can access client-specific features like Project Requests.

---

## 2. The "Hire Our Service" Flow (Client User Flow)

1.  **Request**: The Client submits a project proposal via `POST /api/v1/projects/client/request-project`.
2.  **Consultation**: A Manager sees the `pending` project and schedules a meeting via `POST /api/v1/meetings/create`. The Client receives an email and WebSocket notification.
3.  **Activation**: After the meeting, the Manager updates the project to `active` and assigns a team of Members.
4.  **Execution**: Members work on assigned **Tasks**. The Client can monitor progress through the project dashboard.
5.  **Payment**: Upon completion, the Client pays via the integrated Stripe checkout.
6.  **Auto-Completion**: The `Stripe Webhook` receives the payment confirmation and automatically moves the project status to `completed`.
7.  **Profit Split**: The system triggers a background task (`process_payout_calculation`) that:
    *   Allocates **70%** of the budget to be split equally among the assigned Members.
    *   Allocates **30%** to the Company Wallet (or Client referral wallet).
    *   Credits the respective **Wallets** and records **Transactions**.

---

## 3. The "Work & Earn" Flow (Member User Flow)

1.  **Assignment**: Member is added to a project and assigned specific tasks.
2.  **Notification**: Member receives a real-time notification via WebSockets when a new task is assigned.
3.  **Progress**: Member moves tasks to `in_progress` and finally `completed`.
4.  **Earnings**: Once the project is marked `completed` (via Client payment), the Member's **Wallet** is automatically credited with their share of the profit.
5.  **Withdrawal**:
    *   The Member requests a payout via `POST /api/v1/financials/withdrawals/request`.
    *   The requested amount is placed in escrow (deducted from their balance).
    *   An Admin reviews the request and marks it as `paid` after the bank transfer is initiated.

---

## 4. Product Integration Flow (External Revenue)

1.  **Registration**: Admin adds an external product (e.g., a SaaS app) via `POST /api/v1/products/add`.
2.  **API Key**: The system generates a unique `api_key` for that product.
3.  **Reporting**: The external product sends periodic revenue reports via `POST /api/v1/revenue/report`.
4.  **Treasury**: These funds are automatically added to the **Company Wallet**, allowing the CEO to track global earnings across all TitanCode products.
