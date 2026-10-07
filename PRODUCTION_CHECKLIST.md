# TitanCode — Production Deployment Checklist

> **How to use:** Work through each section top-to-bottom before going live.
> Check off every item (`[x]`) and keep a signed copy with your deployment record.

---

## 1. Environment Variables (Backend)

Set these in your deployment platform (e.g. Render, Railway, Docker `.env`) **before** starting the server.

| Variable | Required | Description | Where to get it |
|---|---|---|---|
| `SECRET_KEY` | ✅ | JWT signing key — must be ≥ 64 random hex chars. Generate with `openssl rand -hex 32` | Generate locally |
| `ALGORITHM` | ✅ | JWT algorithm. Leave as `HS256` unless you have a specific reason to change. | — |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | ✅ | Token lifetime in minutes. `60` is a safe default. | — |
| `ENVIRONMENT` | ✅ | Must be `production` in live deployments. Enables stricter error handling. | — |
| `DATABASE_URL` | ✅ | PostgreSQL connection string: `postgresql+asyncpg://user:pass@host:5432/dbname` | Your DB host |
| `BACKEND_CORS_ORIGINS` | ✅ | Comma-separated list of allowed origins. Tighten to your production domain(s) only. | Your domain |
| `FIRST_SUPERUSER` | ✅ | Email address of the bootstrap admin account. | Set before first run |
| `FIRST_SUPERUSER_PASSWORD` | ✅ | **Change from the default.** Must be strong. | Set before first run |
| `AUTO_SEED_DEFAULT_ADMIN` | ✅ | Set to `false` after the first successful boot to prevent re-seeding. | — |
| `RATE_LIMIT_ENABLED` | ✅ | Set to `true`. Only disable for automated test runs. | — |
| `PAYSTACK_SECRET_KEY` | ✅ | Paystack server-side API key (`sk_live_…`). Required for all transfer operations. | [Paystack Dashboard → Settings → API Keys](https://dashboard.paystack.com/#/settings/developer) |
| `PAYSTACK_PUBLIC_KEY` | ✅ | Paystack client-facing key (`pk_live_…`). Required for inline charge initialisation. | Same as above |
| `FLUTTERWAVE_SECRET_KEY` | ✅ | Flutterwave server-side key (`FLWSECK-…`). Required for multi-currency transfers. | [Flutterwave Dashboard → Settings → APIs](https://app.flutterwave.com/dashboard/settings/apis) |
| `FLUTTERWAVE_WEBHOOK_SECRET` | ✅ | Hash value used to verify incoming Flutterwave webhooks. Without it all Flutterwave webhooks are rejected. | Flutterwave Dashboard → Settings → Webhooks → Hash |
| `STRIPE_SECRET_KEY` | ✅ | Stripe server-side key (`sk_live_…`). Required for Stripe payment intents. | [Stripe Dashboard → Developers → API Keys](https://dashboard.stripe.com/apikeys) |
| `STRIPE_WEBHOOK_SECRET` | ✅ | Endpoint signing secret (`whsec_…`). Used to verify the `Stripe-Signature` header. Without it all Stripe webhooks are rejected. | Stripe Dashboard → Developers → Webhooks → select endpoint → Signing secret |
| `SUMSUB_APP_TOKEN` | ✅ | App token for authenticating Sumsub API calls. Required for KYC applicant creation. | [Sumsub Dashboard → Developers → App tokens](https://api.sumsub.com/checkus#/developers/app-tokens) |
| `SUMSUB_SECRET_KEY` | ✅ | HMAC-SHA256 key. Used for Sumsub API request signing and incoming webhook validation. | Same as above |
| `SUMSUB_WEBHOOK_SECRET` | ✅ | Webhook-level secret set in the Sumsub Webhooks dashboard. Without it all Sumsub webhook events are accepted unverified. | Sumsub Dashboard → Developers → Webhooks |
| `SMTP_HOST` | ⚠️ | SMTP server hostname. If blank, emails are only logged to console (Simulated Mode). | Your email provider |
| `SMTP_PORT` | ⚠️ | SMTP port. Typically `587` (STARTTLS) or `465` (SSL). | Your email provider |
| `SMTP_TLS` | ⚠️ | Set to `true` for STARTTLS. | — |
| `SMTP_USER` | ⚠️ | SMTP login username / email address. | Your email provider |
| `SMTP_PASSWORD` | ⚠️ | SMTP password or app-specific password. | Your email provider |
| `EMAILS_FROM_EMAIL` | ⚠️ | "From" address used in all outgoing emails. Must match your verified sender domain. | — |
| `STORAGE_TYPE` | ⚠️ | Set to `s3` for production. `local` storage is not viable inside containers. | — |
| `AWS_ACCESS_KEY_ID` | ⚠️ | AWS access key for S3 uploads. Required when `STORAGE_TYPE=s3`. | AWS IAM Console |
| `AWS_SECRET_ACCESS_KEY` | ⚠️ | AWS secret for S3. Required when `STORAGE_TYPE=s3`. | AWS IAM Console |
| `S3_BUCKET` | ⚠️ | S3 bucket name for file uploads. | AWS S3 Console |
| `SENTRY_DSN` | ⚠️ | Sentry project DSN for error tracking. Highly recommended in production. | [sentry.io](https://sentry.io) |

---

## 2. Environment Variables (Frontend)

Set these in your frontend deployment platform (Vercel Project Settings → Environment Variables).

| Variable | Required | Description |
|---|---|---|
| `VITE_API_URL` | ✅ | Full URL of the deployed backend, e.g. `https://api.titancode.tech`. No trailing slash. |
| `VITE_GOOGLE_CLIENT_ID` | ⚠️ | Google OAuth 2.0 Web Client ID. Required for "Sign in with Google". Leave blank to disable. |
| `VITE_ENABLE_SUBDOMAIN_ROUTING` | ⚠️ | Set to `true` only when using separate `titancode.tech` / `app.titancode.tech` domains. |
| `VITE_APP_SUBDOMAIN` | ⚠️ | Subdomain for the app workspace (default: `app`). Used with `VITE_ENABLE_SUBDOMAIN_ROUTING=true`. |
| `VITE_ROOT_DOMAIN` | ⚠️ | Root domain, e.g. `titancode.tech`. Used with `VITE_ENABLE_SUBDOMAIN_ROUTING=true`. |
| `VITE_SLACK_WORKSPACE_URL` | ⚠️ | Slack workspace URL or invite link for team chat redirection. |
| `VITE_SLACK_TEAM_ID` | ⚠️ | Slack Team ID (e.g. `T01234567`) for deep-linking into the Slack client. |
| `VITE_SLACK_INVITE_URL` | ⚠️ | Dedicated invite link for applicant/onboarding onboarding flow. |
| `VITE_WHATSAPP_CONCIERGE_NUMBER` | ⚠️ | WhatsApp number for client project update links (full international format, e.g. `2348000000000`). |
| `VITE_TURN_URL` | ⚠️ | TURN server UDP URL, e.g. `turn:turn.titancode.tech:3478?transport=udp`. Required for WebRTC through firewalls. |
| `VITE_TURNS_URL` | ⚠️ | TURN server TCP/TLS URL, e.g. `turns:turn.titancode.tech:5349?transport=tcp`. |
| `VITE_TURN_USERNAME` | ⚠️ | TURN server credential username. |
| `VITE_TURN_CREDENTIAL` | ⚠️ | TURN server credential password. |

---

## 3. Database

- [ ] Provision a managed PostgreSQL instance (e.g. Render Postgres, Railway, Amazon RDS, Supabase).
- [ ] Set `DATABASE_URL` in backend environment.
- [ ] Run migrations:
  ```bash
  alembic upgrade head
  ```
- [ ] Confirm all required tables exist:
  `users`, `projects`, `tasks`, `meetings`, `wallets`, `transactions`,
  `payout_invoices`, `client_invoices`, `withdrawals`, `company_wallet`,
  `audit_log`, `webhook_events`, `departments`, `products`, `revenues`,
  `applications`
- [ ] Seed the default admin account (first boot with `AUTO_SEED_DEFAULT_ADMIN=true`).
- [ ] Set `AUTO_SEED_DEFAULT_ADMIN=false` immediately after the first successful boot.

---

## 4. Payment Gateway Webhook Registration

For each provider, register the webhook URL in their dashboard **before** processing any live transactions.
The backend must be publicly reachable before you register (use a tunnel like ngrok for staging).

### Paystack
- **Webhook URL:** `https://api.titancode.tech/api/v1/webhooks/paystack`
- **Dashboard:** Paystack → Settings → API Keys → Webhook URL
- **Events to enable:** All `charge.*` and `transfer.*` events

### Flutterwave
- **Webhook URL:** `https://api.titancode.tech/api/v1/webhooks/flutterwave`
- **Dashboard:** Flutterwave → Settings → Webhooks → Add webhook
- **Hash secret:** Copy the generated hash into `FLUTTERWAVE_WEBHOOK_SECRET`
- **Events to enable:** `charge.completed`, `transfer.completed`

### Stripe
- **Webhook URL:** `https://api.titancode.tech/api/v1/webhooks/stripe`
- **Dashboard:** Stripe → Developers → Webhooks → Add endpoint
- **Signing secret:** Copy the `whsec_…` value into `STRIPE_WEBHOOK_SECRET`
- **Events to enable:** `payment_intent.succeeded`, `payment_intent.payment_failed`, `charge.refunded`

---

## 5. Sumsub KYC

- [ ] Obtain a **production** App Token and Secret Key from [Sumsub Dashboard → Developers → App tokens](https://api.sumsub.com/checkus#/developers/app-tokens).
- [ ] Set `SUMSUB_APP_TOKEN`, `SUMSUB_SECRET_KEY`, and `SUMSUB_WEBHOOK_SECRET` in your backend `.env`.
- [ ] Register the webhook URL in the Sumsub Dashboard:
  - **Webhook URL:** `https://api.titancode.tech/api/v1/webhooks/sumsub`
  - **Events to enable:** `applicantReviewed`, `applicantPending`, `applicantPersonalInfoChanged`
- [ ] Confirm you are using the **production** endpoint (`https://api.sumsub.com`) not the sandbox.

---

## 6. WebRTC TURN Server

Without a TURN server, video calls will fail for users behind restrictive corporate firewalls or symmetric NAT.

- [ ] Provision a dedicated TURN server using one of:
  - **Twilio Network Traversal Service** (managed, recommended) — [twilio.com/stun-turn](https://www.twilio.com/docs/stun-turn)
  - **Self-hosted Coturn** on a VM with a public IP — open UDP/3478 and TCP/5349
- [ ] Set frontend environment variables:
  ```
  VITE_TURN_URL=turn:turn.titancode.tech:3478?transport=udp
  VITE_TURNS_URL=turns:turn.titancode.tech:5349?transport=tcp
  VITE_TURN_USERNAME=<credential_username>
  VITE_TURN_CREDENTIAL=<credential_password>
  ```
- [ ] Test video call connectivity through a mobile hotspot (simulates restrictive NAT).

---

## 7. Security Checklist

- [ ] **Change the default admin password.** `FIRST_SUPERUSER_PASSWORD` must not be `TitanCodeAdmin123!` in production.
- [ ] Set `ENVIRONMENT=production` — this controls error detail leakage in API responses.
- [ ] Generate a cryptographically random `SECRET_KEY`:
  ```bash
  openssl rand -hex 32
  ```
- [ ] Tighten `BACKEND_CORS_ORIGINS` to your production domain(s) only — remove `localhost` entries.
- [ ] Confirm `RATE_LIMIT_ENABLED=true`.
- [ ] Set `SENTRY_DSN` for error tracking and alerting.
- [ ] Confirm HTTPS is enforced end-to-end (TLS termination at load balancer / reverse proxy).
- [ ] Ensure the database is not publicly reachable — only accessible from backend network.
- [ ] Rotate all API keys and secrets if they were ever committed to version control or shared in plain text.
- [ ] Review IAM/role permissions: the backend service account should have only the permissions it needs.

---

## 8. Email / SMTP

- [ ] Configure SMTP credentials in your backend environment:
  ```
  SMTP_HOST=smtp.resend.com         # or smtp.sendgrid.net, email-smtp.us-east-1.amazonaws.com, etc.
  SMTP_PORT=587
  SMTP_TLS=true
  SMTP_USER=resend                  # provider-specific
  SMTP_PASSWORD=re_xxxxxxxxxxxxx    # your API key or password
  EMAILS_FROM_EMAIL=noreply@titancode.tech
  EMAILS_FROM_NAME=TitanCode Technologies
  ```
- [ ] Verify your sender domain (SPF + DKIM + DMARC) with your email provider.
- [ ] Send a test email to a real address and confirm delivery and formatting.
- [ ] Confirm `EMAILS_FROM_EMAIL` matches a verified sender address (many providers reject unverified senders).

---

## 9. File Storage

Local storage (`STORAGE_TYPE=local`) writes files to the container filesystem. This is **not viable in production** because:
- Files are lost on every deploy/restart.
- Files are not shared across horizontally-scaled instances.

- [ ] Create an S3-compatible bucket (AWS S3, Cloudflare R2, or Backblaze B2).
- [ ] Create an IAM user with `s3:PutObject`, `s3:GetObject`, and `s3:DeleteObject` permissions scoped to that bucket.
- [ ] Set the following in your backend environment:
  ```
  STORAGE_TYPE=s3
  AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
  AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
  S3_BUCKET=titancode-uploads-prod
  AWS_REGION=us-east-1   # or your bucket's region
  ```
- [ ] Confirm upload and download of a test file through the API before going live.

---

## 10. Pre-Launch Smoke Tests

Run these against the live production URL before announcing launch:

- [ ] `GET /health` returns `200 OK`
- [ ] Admin login works with the production credentials
- [ ] A test webhook can be sent from each provider's dashboard and is received + acknowledged (`200`) by the backend
- [ ] File upload returns a URL and the file is accessible
- [ ] An email is delivered end-to-end
- [ ] A video call room can be created and joined from two different browser sessions

---

*Last updated: see git blame on this file.*
