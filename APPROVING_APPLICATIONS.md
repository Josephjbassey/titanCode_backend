# 📝 Guide: How to Approve an Application

In TitanCode, applications (for departments, projects, etc.) must be approved by a **CEO**, **Admin**, or **Manager** before the associated resource is officially created.

---

## Step 1: Authenticate as an Admin
You need a JWT token with high-level permissions.

1. Open **[Swagger UI](http://localhost:8000/docs)**.
2. Find `POST /api/v1/auth/login`.
3. Enter your admin credentials:
   - **Email**: `admin@titancode.com`
   - **Password**: `TitanCodeAdmin123!`
4. Copy the `access_token` from the JSON response.
5. Click **Authorize** at the top of the Swagger page and paste the token.

---

## Step 2: Find the Application ID
If you don't have the ID yet, you can list all pending applications.

- **Endpoint**: `GET /api/v1/applications/`
- Look for the `"id"` of the application you want to approve.

---

## Step 3: Call the Approve Endpoint
This action is atomic: it updates the application status and performs any necessary side effects (like creating a wallet or project record).

- **Endpoint**: `PATCH /api/v1/applications/{application_id}/approve`
- **Method**: `PATCH`

### Example Request (Curl):
```bash
curl -X 'PATCH' \
  'http://localhost:8000/api/v1/applications/1/approve' \
  -H 'Authorization: Bearer YOUR_TOKEN_HERE' \
  -H 'accept: application/json'
```

---

## Step 4: Verify via WebSockets
If you have the **Real-Time Monitor** ([websocket_test.html](file:///home/jabs/Code/work/titanCode/websocket_test.html)) open, you will instantly see an event like this:

```json
{
  "type": "approval",
  "title": "Application Approved!",
  "message": "Your request for [Department Name] has been successfully approved."
}
```

---

## 🚫 Rejection (Alternative)
If you need to reject an application instead:
- **Endpoint**: `PATCH /api/v1/applications/{application_id}/reject`
- This will also trigger a WebSocket notification notifying the user of the rejection.
