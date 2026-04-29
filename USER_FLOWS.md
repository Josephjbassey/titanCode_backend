# TitanCode Technologies: User & Onboarding Flows (Unified Manual Model)

This document outlines the "Zero-Friction" onboarding and project lifecycle.

---

## 1. The "Zero-Friction" Client Onboarding (Unified Form)

To maximize conversion, we have combined Project Discovery and Account Registration into a single step.

1.  **The Entry Point**: A potential client visits the public "Hire Us" page.
2.  **The Unified Form**: The client fills out a single form with:
    *   **Project Details**: Name, Budget, Description.
    *   **Contact Details**: Full Name, Email, Phone.
3.  **Background Automation**: Upon submission (`POST /api/v1/projects/client/request-project`):
    *   The system checks if the email is already in the database.
    *   If new, it **silently creates a 'Client' account** in the background.
    *   A **pending Project** is created and linked to this account.
4.  **HR Notification**: HR is immediately alerted via email with the lead details.
5.  **Manual Outreach**: HR contacts the client via **WhatsApp** or **Email** to discuss the project. No dashboard login is required from the client.

---

## 2. Team Onboarding Flows

### 👑 CEO / Admin
*   Manages the platform, departments, and high-level financial approvals.

### 💼 Manager
*   Sets up internal project tasks, assigns members, and handles technical communication with the client (externally).

### 👥 HR
*   The primary point of contact for leads. Responsible for moving a client from "Form Submitted" to "Project Active."

### 💻 Member / Applicant
*   Registers manually (`POST /api/v1/auth/register`).
*   Applies to a department and waits for Manager approval.
*   Once approved, they are assigned to active projects and earn a **70% profit share**.

---

## 3. Financial Flow (The 70/30 Split)

1.  **Project Completion**: When the project is ready, the Manager sends a Stripe link to the client manually.
2.  **Payment**: The client pays via Stripe.
3.  **Auto-Payout**: The Stripe Webhook triggers the internal system to:
    *   Credit the **team members (70%)**.
    *   Credit the **company treasury (30%)**.
4.  **Transparency**: All internal users (Members, Managers) see their earnings in their personal Wallets.
