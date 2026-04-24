# 📊 TitanCode Technologies: PM Guide (Manual Client Model)

This guide reflects the decision to **scrap the Client Dashboard** and move to a manual, HR-led onboarding and communication model.

---

## 1. Role Definitions & Permissions Matrix

| Role | Responsibility | Key Permissions |
| :--- | :--- | :--- |
| **CEO/Admin** | Oversight & Payouts | Full access; Manage global treasury. |
| **HR** | Manual Onboarding | Monitor "Hire Us" leads; Contact clients externally. |
| **Manager** | Internal Lead | Setup projects; Assign tasks; Update status. |
| **Member** | Execution | Complete tasks; Earn profit shares. |

---

## 2. The Manual Client Flow (How it Works)

### **A. The "Hire Us" Lead**
Instead of a complex CRM, we use a single point of entry for clients:
*   **The Form**: A simple submission endpoint (`/api/v1/projects/client/request-project`).
*   **The Notification**: HR is alerted to the new lead.

### **B. External Communication**
The Project Manager and HR communicate with the client through:
*   **WhatsApp / Telegram**: For daily updates.
*   **Email**: For formal quotes and meeting invites.
*   **Stripe Links**: For project payments.

---

## 3. Why this Works (PM Benefits)
1.  **Reduced Complexity**: We don't need to maintain a secure client-facing dashboard.
2.  **Personal Touch**: HR/Managers build direct relationships with clients via WhatsApp.
3.  **Internal Efficiency**: The system still automates the "hard parts"—task tracking, project accounting, and the 70/30 profit split distribution.

---

## 4. Technical Workflow Summary
*   **Internal tracking continues**: Even if the client doesn't see it, Managers MUST use the system to track tasks and projects to ensure the **Profit Split Engine** works correctly.
*   **Stripe is the Trigger**: Manual communication ends with a Stripe link. When the client pays, the system handles the rest (Member credits, Company share).

## 7. HR Workflow: Manual Lead Processing

HR plays the critical role of "Gatekeeper" and "Concierge" in the new manual model.

1.  **Lead Reception**: HR receives an automated email for every new submission via the "Hire Us" form.
2.  **Initial Contact**: HR reaches out to the client within 24 hours via **WhatsApp** (using the phone number from the user profile) or **Email**.
3.  **Qualification**: HR assesses the client's needs and budget.
4.  **Meeting Coordination**: HR coordinates with the relevant Department Manager to schedule a manual meeting (Zoom/Meet/WhatsApp Call).
5.  **Project Handoff**: Once the deal is closed, HR hands the project details to the Manager, who then activates the project internally in the TitanCode platform.
