# 📊 TitanCode Technologies: Project Manager's Guide

This document provides a complete overview of the TitanCode ecosystem, designed for Project Managers to understand user flows, role responsibilities, and the underlying technical architecture.

---

## 1. Role Definitions & Permissions Matrix

The platform uses **Role-Based Access Control (RBAC)**. Every user is assigned a specific role that dictates their visibility and action limits.

| Role | Responsibility | Key Permissions |
| :--- | :--- | :--- |
| **CEO** | Global oversight | Full access; Delete anything; Manage all wallets. |
| **Admin** | System operations | Manage users; Approve withdrawals; Register external products. |
| **Manager** | Department lead | Approve applications; Create/Assign projects & tasks; Schedule meetings. |
| **Member** | Project execution | View assigned tasks; Update work status; Request payouts. |
| **Client** | Service hiring | Request projects; Participate in meetings; Pay for services. |
| **Applicant**| Waiting to join | View departments; Submit membership application. |

---

## 2. The Client Journey: Navigation & Access

### **A. Onboarding**
1.  **Sign-up**: The client registers at `/auth/register`.
2.  **Activation**: An Admin validates the client and upgrades their role from `Member` to `Client` via the User Update endpoint.

### **B. Navigating the Dashboard**
*   **Project Request**: Clients access the "Hire Us" section where they submit a **Project Request** (Budget, Description, Deadline).
*   **Meeting Room**: Clients see a list of scheduled video/audio consultations. They receive a "Join" link when a session is active.
*   **Active Projects**: A dedicated view showing the progress bar of their active projects and a list of high-level task completions.
*   **Billing & Payments**:
    *   Clients see "Invoices" for their projects.
    *   Clicking **"Pay Now"** redirects them to a Stripe Checkout page.
    *   Once paid, the project is marked as "Completed" in real-time via Webhooks.

---

## 3. The Core Business Workflow

### **Phase 1: Sales & Onboarding**
*   **User Flow**: Applicant → Registration → Application Submission → Manager Review → Approved Member.
*   **Client Flow**: Registration → Admin Approval → Project Request submission.

### **Phase 2: Project Management**
1.  **Discovery**: Manager sees a new project request and schedules a **Meeting**.
2.  **Assignment**: Manager sets project to "Active" and assigns a **Team** (Members) and a **Lead** (Manager).
3.  **Execution**: Manager breaks down the project into **Tasks** and assigns them to Members.
4.  **Notifications**: Every assignment triggers a **WebSocket notification** to the Member's dashboard and an **Email** to their inbox.

### **Phase 3: Financial Settlement (The "Engine")**
*   **Completion**: When the project is finished, the Client pays.
*   **Payout Logic**: The system automatically executes the **70/30 split**:
    *   **70%** distributed to the working team's personal wallets.
    *   **30%** retained in the Company Treasury.
*   **Withdrawal**: Members can request their funds, which an Admin then approves and processes.

---

## 4. Technical Architecture: How the Codebase Works

The codebase is built on a **Modular Micro-Services** approach using the following stack:

### **A. The API Layer (FastAPI)**
*   Located in `/app/api/v1/endpoints/`.
*   Each file represents a business domain (e.g., `projects.py`, `wallets.py`).
*   It handles security, input validation, and communication with the database.

### **B. The Database (PostgreSQL & SQLAlchemy)**
*   Located in `/app/db/`.
*   Stores everything: User profiles, financial transactions, project statuses, and encrypted password hashes.

### **C. The Task Engine (Celery & Redis)**
*   Located in `/app/tasks/`.
*   Handles **background processing** that is too slow for the main API (e.g., calculating complex profit splits, sending bulk emails, processing Stripe webhooks).
*   **Redis** acts as the "messenger" between the API and the Task Engine.

### **D. Real-time Communication (WebSockets)**
*   Located in `/app/core/notifications.py`.
*   Provides instant updates. When a Manager clicks "Approve", the Member's screen updates immediately without a refresh.

---

## 5. Summary for PMs
1.  **Trust the Status**: A project only triggers payouts when its status hits `completed`.
2.  **RBAC is Key**: If a user can't see something, check their `role` in the `users` table.
3.  **Auditable**: Every cent moved in the system is recorded in the `transactions` table—never delete rows, always "soft-delete" or update status.

## 6. Detailed Client Dashboard Navigation (UI Walkthrough)

To assist with UI/UX planning, here is how a Client navigates the platform:

1. **Top Navigation Bar**:
   - **Dashboard**: Overview of total projects and spending.
   - **Hire Services**: Button to trigger the Project Request form.
   - **Meetings**: Calendar view of scheduled sessions.
   - **Invoices**: List of pending and paid invoices.

2. **Project Detail View**:
   - **Progress Tracker**: Visual indicator of project status (Pending -> Active -> Completed).
   - **Team List**: Names and roles (but not personal contact info) of the assigned TitanCode members.
   - **Deliverables**: Links to files uploaded by the team (via the `/files` module).

3. **Interaction Flow**:
   - **Step 1**: Client fills in a form (Name, Description, Budget).
   - **Step 2**: Client receives a notification when a Manager is assigned.
   - **Step 3**: Client clicks "Join Meeting" directly from their dashboard.
   - **Step 4**: Upon project completion, a "Pay & Finalize" button appears, linking to Stripe.
