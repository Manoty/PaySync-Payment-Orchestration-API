# PaySync

**Unified Payment Infrastructure for Modern Applications**

PaySync is a production-ready payment orchestration API that wraps the Safaricom M-Pesa Daraja API into a clean, centralized payment layer. Built for [Tixora](https://tixora.co.ke) (ticket payments) and [Scott](https://scott.co.ke) (delivery payments), it handles everything from STK Push initiation to callback processing, retry logic, and status normalization — so your applications never have to touch M-Pesa directly.

---

## Table of Contents

- [Why PaySync](#why-paysync)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [API Reference](#api-reference)
- [Authentication](#authentication)
- [Payment Lifecycle](#payment-lifecycle)
- [Retry Logic](#retry-logic)
- [Status Normalization](#status-normalization)
- [Security](#security)
- [Logging & Observability](#logging--observability)
- [Management Commands](#management-commands)
- [Deployment](#deployment)
- [Integration Guide](#integration-guide)

---

## Why PaySync

Without a centralized payment layer, every system that needs M-Pesa must implement it independently:

```
❌ Without PaySync
Tixora → its own M-Pesa code → duplicated logic
Scott  → its own M-Pesa code → duplicated logic
```

```
✅ With PaySync
Tixora ──┐
          ├──→ PaySync API ──→ M-Pesa
Scott  ──┘
```

**Benefits:**
- One place to fix bugs — all consumers benefit immediately
- One audit trail for every payment across all systems
- One retry system, one status format, one callback handler
- Consumer systems never know M-Pesa exists — only `pending`, `success`, or `failed`

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Tixora / Scott                       │
│          POST /payments/initiate/                        │
│          GET  /payments/{ref}/status/                    │
└────────────────────┬────────────────────────────────────┘
                     │  X-API-Key authentication
                     ▼
┌─────────────────────────────────────────────────────────┐
│                      PaySync API                         │
│                                                          │
│  Validate → Idempotency check → Create Payment           │
│  → Fire STK Push → Await Callback → Normalize Status     │
│  → Schedule Retry (if needed) → Return clean status      │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│                   M-Pesa Daraja API                      │
│                                                          │
│  Receive STK Push → Notify Customer Phone                │
│  → Customer enters PIN → Send callback to PaySync        │
└─────────────────────────────────────────────────────────┘
```

### Data Model

```
Payment (1)
    └── PaymentAttempt (many)   ← one per STK Push attempt
            └── CallbackLog (many)  ← raw M-Pesa callbacks
```

| Model | Purpose |
|---|---|
| `Payment` | Single source of truth per payment intention |
| `PaymentAttempt` | Full history of every STK Push attempt |
| `CallbackLog` | Every raw M-Pesa callback, stored before processing |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | Django + Django REST Framework |
| Database | PostgreSQL |
| M-Pesa | Safaricom Daraja API (STK Push) |
| Auth | API Key (SHA-256 hashed, never stored raw) |
| Scheduling | Windows Task Scheduler (retry processor) |
| Logging | Structured JSON logs (rotating files) |

---

## Project Structure

```
paysync/
├── paysync_backend/
│   ├── settings/
│   │   ├── __init__.py       # Loads correct settings based on DJANGO_ENV
│   │   ├── base.py           # Shared settings
│   │   ├── development.py    # Local dev overrides
│   │   ├── production.py     # Production hardening
│   │   └── testing.py        # Test suite settings
│   ├── error_handlers.py     # Normalized DRF exception handler
│   ├── log_formatter.py      # Structured JSON + human-readable formatters
│   ├── middleware.py          # Request/response logging middleware
│   └── urls.py               # Root URL config
│
├── payments/
│   ├── models.py             # Payment, PaymentAttempt, CallbackLog
│   ├── views.py              # API views
│   ├── serializers.py        # Input/output serializers
│   ├── urls.py               # Payment endpoint routes
│   ├── mpesa_service.py      # Daraja API wrapper
│   ├── callback_processor.py # M-Pesa callback handler
│   ├── retry_service.py      # Retry scheduling and execution
│   ├── status_normalizer.py  # M-Pesa codes → PaySync statuses
│   ├── validators.py         # Phone, amount, reference validators
│   ├── event_logger.py       # Structured payment event logger
│   ├── health.py             # System health checks
│   └── management/commands/
│       ├── process_retries.py    # Trigger retry processing
│       ├── replay_callbacks.py   # Replay failed callbacks
│       ├── analyze_logs.py       # Log analysis and metrics
│       └── production_check.py   # Pre-deployment checklist
│
├── authentication/
│   ├── models.py             # APIClient, APIRequestLog
│   ├── backends.py           # API key authentication backend
│   ├── permissions.py        # IsAuthenticatedAPIClient, SourceSystemMatch
│   ├── rate_limiter.py       # Sliding window rate limiter
│   ├── mpesa_ip_validator.py # M-Pesa callback IP allowlist
│   └── management/commands/
│       └── manage_api_clients.py # Create/list/revoke API clients
│
├── paysync_clients/          # Integration simulations
│   ├── paysync_client.py     # Shared PaySync HTTP client
│   ├── tixora_simulation.py  # Tixora payment flow simulation
│   ├── scott_simulation.py   # Scott payment flow simulation
│   └── integration_test.py   # Cross-system integration tests
│
├── logs/                     # Rotating log files (auto-created)
│   ├── payments.log          # All payment lifecycle events (JSON)
│   ├── errors.log            # ERROR + CRITICAL only (JSON)
│   └── paysync.log           # General application events (JSON)
│
├── .env                      # Local secrets (never committed)
├── .env.production           # Production template (no real values)
├── requirements.txt
├── validate_env.py           # Pre-start env variable validator
├── run_retries.ps1           # Task Scheduler retry runner
└── deploy_checklist.ps1      # Pre-deployment verification script
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL 14+
- PowerShell (Windows)
- [ngrok](https://ngrok.com) (for sandbox callback testing)
- A [Safaricom Daraja](https://developer.safaricom.co.ke) sandbox account

### Installation

```powershell
# 1. Clone and navigate
git clone https://github.com/yourorg/paysync.git
cd paysync

# 2. Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create PostgreSQL database
psql -U postgres -c "CREATE DATABASE paysync_db;"
psql -U postgres -c "CREATE USER paysync_user WITH PASSWORD 'your_password';"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE paysync_db TO paysync_user;"

# 5. Configure environment
copy .env.example .env
# Edit .env with your credentials

# 6. Validate environment variables
python validate_env.py

# 7. Apply migrations
python manage.py migrate

# 8. Create API clients for Tixora and Scott
python manage.py manage_api_clients create --name "Tixora" --source-system tixora
python manage.py manage_api_clients create --name "Scott" --source-system scott

# 9. Create admin user
python manage.py createsuperuser

# 10. Start the server
python manage.py runserver
```

---

## Environment Variables

Create a `.env` file in the project root:

```env
# Django
DJANGO_ENV=development
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
DB_NAME=paysync_db
DB_USER=paysync_user
DB_PASSWORD=your_db_password
DB_HOST=localhost
DB_PORT=5432

# M-Pesa Daraja
MPESA_CONSUMER_KEY=your_consumer_key
MPESA_CONSUMER_SECRET=your_consumer_secret
MPESA_SHORTCODE=174379
MPESA_PASSKEY=your_passkey
MPESA_CALLBACK_URL=https://your-ngrok-url.ngrok.io/api/v1/payments/callback/
MPESA_ENV=sandbox

# CORS (production only)
CORS_ALLOWED_ORIGINS=https://tixora.co.ke,https://scott.co.ke
```

> **Sandbox test number:** `254708374149`  
> **Sandbox shortcode:** `174379`  
> **Sandbox passkey:** `bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919`

---

## API Reference

All endpoints are prefixed with `/api/v1/`. All responses follow this envelope:

```json
{
  "success": true,
  "message": "Human readable message",
  "data": { }
}
```

```json
{
  "success": false,
  "message": "What went wrong",
  "errors": { }
}
```

---

### POST `/payments/initiate/`

Initiates an M-Pesa STK Push to the customer's phone.

**Headers:**
```
Content-Type: application/json
X-API-Key: paysync_your_api_key_here
```

**Request:**
```json
{
  "amount": 1500,
  "phone_number": "0712345678",
  "external_reference": "ORDER_123",
  "source_system": "tixora"
}
```

| Field | Type | Rules |
|---|---|---|
| `amount` | integer | Min: 1, Max: 150,000, whole numbers only |
| `phone_number` | string | Safaricom numbers only. Accepts `07...`, `2547...`, `+2547...` |
| `external_reference` | string | Your order/delivery ID. Alphanumeric + dashes/underscores. Max 100 chars |
| `source_system` | string | `tixora` or `scott` — must match your API key registration |

**Response `201`:**
```json
{
  "success": true,
  "message": "STK Push sent. Awaiting customer PIN entry.",
  "data": {
    "reference": "a3f9c2d1-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "external_reference": "ORDER_123",
    "source_system": "tixora",
    "amount": "1500.00",
    "phone_number": "254712345678",
    "status": "pending",
    "provider": "mpesa",
    "retry_count": 0,
    "next_retry_at": null,
    "attempts": [
      {
        "attempt_number": 1,
        "status": "initiated",
        "mpesa_checkout_request_id": "ws_CO_...",
        "error_message": null,
        "created_at": "2024-01-15T10:30:01Z"
      }
    ],
    "created_at": "2024-01-15T10:30:01Z",
    "updated_at": "2024-01-15T10:30:01Z"
  }
}
```

**Idempotency:** Submitting the same `external_reference` + `source_system` while a payment is `pending` or `success` returns the existing payment with HTTP `200` — no duplicate STK Push is fired.

---

### GET `/payments/{reference}/status/`

Lightweight status check. Poll this after initiation.

**Headers:**
```
X-API-Key: paysync_your_api_key_here
```

**Response `200` — success:**
```json
{
  "success": true,
  "data": {
    "reference": "a3f9c2d1-...",
    "status": "success",
    "amount": "1500.00",
    "retry_count": 0,
    "next_retry_at": null,
    "message": "Payment completed successfully."
  }
}
```

**Response `200` — retry pending:**
```json
{
  "success": true,
  "data": {
    "status": "pending",
    "retry_count": 1,
    "next_retry_at": "2024-01-15T10:32:00Z",
    "message": "Previous attempt failed. Retry scheduled."
  }
}
```

**Response `200` — permanent failure:**
```json
{
  "success": true,
  "data": {
    "status": "failed",
    "retry_count": 0,
    "next_retry_at": null,
    "failure_reason": "[1032] Transaction cancelled by user",
    "message": "Payment failed. No further retries will be made."
  }
}
```

---

### GET `/payments/{reference}/`

Full payment detail including all attempt history.

---

### GET `/payments/`

List payments with optional filters.

| Query param | Example | Description |
|---|---|---|
| `source_system` | `?source_system=tixora` | Filter by system |
| `status` | `?status=success` | Filter by status |
| `external_reference` | `?external_reference=ORDER_123` | Find by your reference |
| `phone_number` | `?phone_number=254712345678` | Filter by phone |

---

### GET `/api/v1/health/`

Public endpoint. No API key required.

**Returns `200` if healthy, `503` if unhealthy.**

```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:01Z",
  "response_ms": 12,
  "environment": "sandbox",
  "checks": {
    "database":       { "status": "ok", "latency_ms": 3 },
    "mpesa_config":   { "status": "ok", "environment": "sandbox" },
    "payment_stats":  { "status": "ok", "total": 42, "failure_rate": "4.8%" },
    "retry_queue":    { "status": "ok", "scheduled": 2, "overdue": 0 }
  }
}
```

---

### POST `/payments/callback/`

**Internal — do not call this directly.**  
This endpoint receives POST requests from Safaricom's Daraja servers. Protected by M-Pesa IP allowlisting.

---

## Authentication

PaySync uses API keys passed in the `X-API-Key` header.

### Create an API client

```powershell
python manage.py manage_api_clients create \
  --name "Tixora Production" \
  --source-system tixora \
  --rate-limit 60
```

The raw key is shown **once** at creation and never again. Store it securely.

### Use the key

```http
POST /api/v1/payments/initiate/
X-API-Key: paysync_a3f9c2d1e4b5f6...
Content-Type: application/json
```

### Key properties

| Property | Detail |
|---|---|
| Format | `paysync_` prefix + 64 hex characters |
| Storage | SHA-256 hash stored — raw key never persisted |
| Binding | Each key is bound to one `source_system` |
| Rate limit | Configurable per client (default: 30 req/min) |
| Revocation | `python manage.py manage_api_clients revoke --source-system tixora` |

---

## Payment Lifecycle

```
Created (pending)
    │
    ▼
STK Push sent to customer phone
    │
    ├── Customer enters PIN
    │       │
    │       ▼
    │   Callback received from M-Pesa
    │       │
    │       ├── ResultCode 0  ───────────────────▶ SUCCESS ✅
    │       │
    │       ├── Permanent failure (1032/2001/1001) ▶ FAILED ❌ (no retry)
    │       │
    │       └── Retryable failure (1037/timeout)  ▶ Retry scheduled ⏳
    │
    └── STK Push failed (network/Daraja error)    ▶ Retry scheduled ⏳
                │
                ▼
        [2 min later] Retry attempt #2
                │
                ▼
        [5 min later] Retry attempt #3
                │
                ▼
        [10 min later] Retry attempt #4
                │
                ▼
        Max retries reached ──────────────────────▶ FAILED ❌ (permanent)
```

---

## Retry Logic

PaySync automatically retries failed payments using exponential backoff.

| Attempt | Delay before retry |
|---|---|
| 1 → 2 | 2 minutes |
| 2 → 3 | 5 minutes |
| 3 → 4 | 10 minutes |
| After attempt 4 | Permanently failed |

### What gets retried

| M-Pesa Result Code | Meaning | Retried? |
|---|---|---|
| `0` | Success | N/A |
| `1032` | Cancelled by user | ❌ No |
| `2001` | Wrong PIN | ❌ No |
| `1001` | Insufficient funds | ❌ No |
| `1037` | Customer unreachable | ✅ Yes |
| `1019` | Transaction expired | ✅ Yes |
| Network timeout | Daraja unreachable | ✅ Yes |

### Setup the retry scheduler (Windows)

```powershell
# Register with Windows Task Scheduler (run as Administrator)
$action  = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-File C:\Projects\paysync\run_retries.ps1"
$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 1) -Once -At (Get-Date)
Register-ScheduledTask -TaskName "PaySync_RetryPayments" -Action $action -Trigger $trigger
```

---

## Status Normalization

No consumer ever sees an M-Pesa result code. Every payment has exactly one of three statuses:

| PaySync Status | Meaning |
|---|---|
| `pending` | STK Push sent, or retry scheduled |
| `success` | Customer paid — confirmed by M-Pesa callback |
| `failed` | All attempts exhausted, or permanent failure |

Adding a new payment provider (e.g. Airtel Money) requires only:
1. Create `AirtelStatusNormalizer` with the same interface
2. Register: `StatusNormalizerFactory.register('airtel', AirtelStatusNormalizer)`
3. Zero changes to views, callbacks, or consumer systems

---

## Security

| Layer | Mechanism |
|---|---|
| Authentication | `X-API-Key` header, SHA-256 hashed at rest |
| Authorization | API key bound to `source_system` — Tixora cannot initiate as Scott |
| Rate limiting | Sliding window, per-client, configurable |
| Callback protection | M-Pesa IP allowlist (Safaricom's published ranges) |
| Phone validation | Safaricom-prefix check, format normalization |
| Amount validation | Min 1, max 150,000, whole numbers only |
| Secret management | All credentials in `.env`, never in source code |
| HTTPS | Enforced in production with HSTS |
| CORS | Locked to registered origins in production |

---

## Logging & Observability

All logs are structured JSON — every field is queryable.

### Log files

| File | Contents | Rotation |
|---|---|---|
| `logs/payments.log` | All payment lifecycle events | 10MB × 20 |
| `logs/errors.log` | ERROR + CRITICAL only | 5MB × 20 |
| `logs/paysync.log` | General application events | 10MB × 10 |

### Sample log entry

```json
{
  "timestamp": "2024-01-15T10:30:01.123Z",
  "level": "INFO",
  "logger": "payments",
  "message": "Payment confirmed successful",
  "event": "payment_succeeded",
  "reference": "a3f9c2d1-...",
  "source_system": "tixora",
  "amount": 1500.0,
  "mpesa_receipt": "PH700000001",
  "retry_count": 0
}
```

### Query logs

```powershell
# All events for one payment
Get-Content logs\payments.log | python -c "
import sys, json
for line in sys.stdin:
    e = json.loads(line)
    if e.get('reference') == 'YOUR-UUID':
        print(json.dumps(e, indent=2))
"

# All critical alerts
Get-Content logs\errors.log | python -c "
import sys, json
for line in sys.stdin:
    e = json.loads(line)
    if e.get('level') == 'CRITICAL':
        print(e['timestamp'], '|', e['message'])
"
```

---

## Management Commands

```powershell
# API client management
python manage.py manage_api_clients create --name "Tixora" --source-system tixora --rate-limit 60
python manage.py manage_api_clients list
python manage.py manage_api_clients revoke --source-system tixora

# Payment operations
python manage.py process_retries              # Process all due retries
python manage.py process_retries --dry-run   # Preview without executing
python manage.py replay_callbacks            # Replay unprocessed callbacks
python manage.py replay_callbacks --id 42   # Replay specific callback

# Observability
python manage.py analyze_logs               # Analyze recent payment logs
python manage.py analyze_logs --event stk_push_failed
python manage.py analyze_logs --lines 500

# Deployment
python manage.py production_check           # Pre-deployment readiness check
python manage.py migrate                    # Apply DB migrations
python manage.py collectstatic              # Collect static files
```

---

## Deployment

### Pre-deployment checklist

```powershell
# Set production environment
$env:DJANGO_ENV = "production"

# Validate environment variables
python validate_env.py

# Run full production readiness check
python manage.py production_check

# Apply migrations
python manage.py migrate

# Run Django's own deployment checks
python manage.py check --deploy

# Collect static files
python manage.py collectstatic --noinput

# Or run everything at once
.\deploy_checklist.ps1
```

### Switch environments

```env
# .env
DJANGO_ENV=development   # or production or testing
```

### Production requirements

- [ ] `DEBUG=False`
- [ ] `MPESA_ENV=production` (not sandbox)
- [ ] `MPESA_CALLBACK_URL` is HTTPS and publicly reachable
- [ ] `ALLOWED_HOSTS` set to your domain
- [ ] `CORS_ALLOWED_ORIGINS` locked to Tixora/Scott domains
- [ ] Retry scheduler registered with Windows Task Scheduler
- [ ] API clients created for Tixora and Scott
- [ ] `logs/` directory exists and is writable

---

## Integration Guide

### Tixora / Scott — How to call PaySync

```python
import requests

PAYSYNC_BASE = "https://api.paysync.yourdomain.com/api/v1"
API_KEY      = "paysync_your_key_here"

headers = {
    "Content-Type": "application/json",
    "X-API-Key":    API_KEY,
}

# 1. Initiate payment
response = requests.post(f"{PAYSYNC_BASE}/payments/initiate/", headers=headers, json={
    "amount":             1500,
    "phone_number":       "0712345678",
    "external_reference": "ORDER_123",
    "source_system":      "tixora",
})

reference = response.json()["data"]["reference"]

# 2. Poll for status
import time
for _ in range(24):              # Poll for up to 2 minutes
    time.sleep(5)
    status_resp = requests.get(
        f"{PAYSYNC_BASE}/payments/{reference}/status/",
        headers=headers,
    )
    status = status_resp.json()["data"]["status"]

    if status == "success":
        confirm_order()
        break
    elif status == "failed" and not status_resp.json()["data"]["next_retry_at"]:
        cancel_order(status_resp.json()["data"]["failure_reason"])
        break
```

### What your system should store

After a successful initiation, store:

| Field | Why |
|---|---|
| `reference` (UUID) | PaySync's internal ID — use this for all status checks |
| `external_reference` | Your order ID — already know this |

That's all. PaySync owns everything else.

---

## Contributing

1. Branch from `main`
2. Make changes incrementally — one concern per commit
3. Run `python manage.py test` before pushing
4. Run `python manage.py production_check` before merging to main

---

## License

MIT — see [LICENSE](LICENSE)

---

*PaySync — built for Tixora and Scott. Simplified in design, serious in reliability.*
