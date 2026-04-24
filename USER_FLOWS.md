# TitanCode Technologies: User & Onboarding Flows (Manual Client Model)

This document outlines the end-to-end lifecycle for every role within the platform. **Note: Based on PM requirements, the Client Dashboard has been removed in favor of a manual HR-led onboarding process.**

---

## 1. Onboarding Flows (By Role)

### 👑 CEO / Admin
*   **Onboarding**: Bootstrapped automatically or promoted by the CEO.
*   **Responsibility**: Managing departments, approving high-level withdrawals, and overseeing the "Company Wallet."

### 💼 Manager (Department Lead)
*   **Promotion**: Updated by Admin/CEO.
*   **Responsibility**: Receives leads from HR, creates project records manually, and assigns members/tasks.

### 👥 HR (New Role: Manual Onboarding Lead)
*   **Responsibility**: Monitors the "Hire Us" form submissions, contacts potential clients via Email/WhatsApp, and facilitates the manual onboarding of projects into the system.

### 💻 Member / Applicant (The Talent)
*   **Step 1: Registration**: Signs up via `POST /api/v1/auth/register`.
*   **Step 2: Application**: Submits GitHub/Portfolio via `POST /api/v1/applications/apply`.
*   **Step 3: Approval**: Manager approves application, activating the user and assigning them to a department.

### 🤝 Client (Manual "Hire Us" Flow)
*   **No Dashboard Access**: Clients do not log in to a dashboard for project management.
*   **Onboarding**:
    1. Client fills out a public "Hire Us" form (Project Request).
    2. HR receives the request and contacts the Client via WhatsApp/Email.
    3. HR/Manager handles all project communication externally.
    4. Project is tracked internally by the TitanCode team.

---

## 2. The "Hire Our Service" Flow (Manual Process)

1.  **Lead Generation**: A potential client submits a "Hire Us" form (`POST /api/v1/projects/client/request-project`).
2.  **HR Outreach**: HR receives a notification, reviews the budget/description, and contacts the Client via WhatsApp/Email.
3.  **Discovery & Quote**: A meeting is held (external to the app, or via internal meeting links sent manually).
4.  **Internal Setup**: Once the client agrees, a Manager creates or activates the Project in the TitanCode system for internal tracking.
5.  **Execution**: Members work on tasks. The Client is updated manually by the Manager/HR via their preferred communication channel (WhatsApp/Slack/Email).
6.  **Payment**: Client pays via a Stripe link sent manually by the Manager.
7.  **Auto-Payout**: Stripe Webhook triggers the internal status to "Completed," and the 70/30 profit split is automatically distributed to the team's wallets.

---

## 3. The "Work & Earn" Flow (Member User Flow)

1.  **Assignment**: Member is assigned tasks by the Manager.
2.  **Notification**: Member receives a real-time notification on their dashboard.
3.  **Reward**: Upon project completion (verified by Stripe), the Member's **Wallet** is credited automatically.
4.  **Withdrawal**: Member requests a payout, which is processed by an Admin.
