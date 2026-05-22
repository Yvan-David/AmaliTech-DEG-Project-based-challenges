# Pulse-Check API — Watchdog Sentinel

A **Dead Man's Switch API** for monitoring remote devices (solar farms, weather stations, unmanned infrastructure). Devices register a monitor with a countdown timer and must send periodic heartbeats to stay "alive." If a device goes silent, the system automatically fires an alert email and logs the failure.

Built with **FastAPI**, **Redis (Upstash)**, and **Resend**.

---

## Table of Contents

- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Setup & Installation](#setup--installation)
- [Environment Variables](#environment-variables)
- [Running the Server](#running-the-server)
- [Running Tests](#running-tests)
- [API Documentation](#api-documentation)
- [Developer's Choice: Webhook Alerts](#developers-choice-webhook-alerts)
- [Design Decisions](#design-decisions)

---

## Architecture

### Sequence Diagram

![Pulse Check Architecture Diagram1](assets/sequence-diagram1.png)
![Pulse Check Architecture Diagram2](assets/sequence-diagram2.png)

[live link](https://lucid.app/lucidchart/bf38fad2-3468-4840-ae97-09adff426742/edit?viewport_loc=271%2C539%2C1469%2C699%2C0_0&invitationId=inv_9ebd47d9-e2db-4c3e-8c42-a20c363821ad) LOGIN REQUIRED
### Redis Key Schema

Two keys are stored per monitor:

| Key | TTL | Purpose |
|-----|-----|---------|
| `monitor:{id}` | none | JSON blob — full monitor state, survives expiry |
| `monitor:{id}:timer` | `timeout` seconds | Countdown — its disappearance triggers the alert |

The data key has no TTL so the watcher can read the device's email and status even after the timer fires. Storing state and countdown in one key would delete all context on expiry.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | FastAPI (Python) |
| Data store | Redis via Upstash (REST API) |
| Email alerts | Resend |
| Background timer | Daemon thread polling Redis TTLs every second |
| Testing | pytest + pytest-asyncio + fakeredis |

---

## Setup & Installation

### Prerequisites

- Python 3.11+
- An [Upstash](https://upstash.com) account (free tier works)
- A [Resend](https://resend.com) account (free tier works)

### Install dependencies

```bash
git clone https://github.com/your-username/AmaliTech-DEG-Project-based-challenges/backend/Pulse-Check.git
cd pulse-check-api
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

## Environment Variables

Create a `.env` file in the project root:

```env
# Redis
REDIS_URL=https://your-endpoint.redis.io


# Resend — from resend.com → API Keys
RESEND_API_KEY=re_xxxxxxxxxxxxxxxx
ALERT_FROM_EMAIL=alerts@yourdomain.com   # must be verified in Resend
```

> **Note:** Never commit `.env` to version control. It is already listed in `.gitignore`.

---

## Running the Server

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.

Interactive docs (Swagger UI): `http://localhost:8000/docs`

---

## Running Tests

Tests use `fakeredis` — no real Redis connection or credentials needed.

```bash
pytest
```

With coverage:

```bash
pytest --cov=app --cov-report=term-missing
```

---

## API Documentation

### Base URL

```
http://localhost:8000
```

---

### `GET /health`

Check that the server is running.

**Response `200 OK`**
```json
{ "status": "ok" }
```

---

### `POST /monitors`

Register a new monitor and start the countdown timer. If the ID already exists, it is replaced and the timer restarts.

**Request Body**
```json
{
  "id": "device-123",
  "timeout": 60,
  "alert_email": "admin@critmon.com",
  "webhook_url": "https://hooks.example.com/alert"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | ✅ | Unique device identifier |
| `timeout` | integer > 0 | ✅ | Countdown duration in seconds |
| `alert_email` | string (email) | ✅ | Email address to alert when device goes down |
| `webhook_url` | string (URL) | ❌ | Optional webhook to POST alert payload to |

**Response `201 Created`**
```json
{
  "message": "Monitor registered.",
  "monitor_id": "device-123",
  "status": "active",
  "expires_at": "2025-06-23T18:50:00Z"
}
```

---

### `POST /monitors/{id}/heartbeat`

Reset the countdown timer for a device. Also un-pauses a paused monitor.

**Response `200 OK`**
```json
{
  "message": "Heartbeat received. Timer reset.",
  "monitor_id": "device-123",
  "status": "active",
  "expires_at": "2025-06-23T18:51:00Z"
}
```

**Error responses**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | Monitor ID does not exist |
| `409 Conflict` | Monitor has already gone down — must re-register with `POST /monitors` |

---

### `POST /monitors/{id}/pause`

Freeze the countdown. No alert will fire while paused. Send a heartbeat to resume.

**Response `200 OK`**
```json
{
  "message": "Monitor paused.",
  "monitor_id": "device-123",
  "status": "paused",
  "expires_at": "2025-06-23T18:50:00Z"
}
```

**Error responses**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | Monitor ID does not exist |

---

### `GET /monitors/{id}`

Fetch the current state of a monitor, including seconds remaining on the countdown.

**Response `200 OK`**
```json
{
  "id": "device-123",
  "timeout": 60,
  "alert_email": "admin@critmon.com",
  "webhook_url": null,
  "status": "active",
  "created_at": "2025-06-23T18:49:00Z",
  "expires_at": "2025-06-23T18:50:00Z",
  "last_heartbeat": "2025-06-23T18:49:30Z",
  "alert_count": 0,
  "seconds_remaining": 30
}
```

---

### `GET /monitors`

List all registered monitors.

**Response `200 OK`**
```json
[
  {
    "id": "device-123",
    "status": "active",
    ...
  },
  {
    "id": "device-456",
    "status": "paused",
    ...
  }
]
```

---

### `DELETE /monitors/{id}`

Remove a monitor and cancel its countdown. No alert will fire after deletion.

**Response `204 No Content`**

**Error responses**

| Status | Condition |
|--------|-----------|
| `404 Not Found` | Monitor ID does not exist |

---

### Alert Payload (fired internally when timer expires)

When a device goes down, the following is logged to the console and sent via email:

```json
{
  "ALERT": "Device device-123 is down!",
  "time": "Monday, 23 Jun 2025 at 8:50 PM",
  "alert_email": "admin@critmon.com",
  "alert_count": 1
}
```

The time is displayed in **Central Africa Time (CAT, UTC+2)** — Rwanda local time.

---

## Developer's Choice: Webhook Alerts

**Feature:** An optional `webhook_url` field on monitor registration.

**Why:** Email alerts are reliable but asynchronous — an engineer may not see them immediately. A webhook delivers the alert payload via HTTP POST directly to any endpoint: a Slack bot, a PagerDuty integration, a custom dashboard, or a mobile push notification service. This makes the system extensible without coupling it to any specific notification platform.

**How it works:**

1. Register a monitor with a `webhook_url`:
```json
{
  "id": "solar-farm-7",
  "timeout": 3600,
  "alert_email": "ops@critmon.com",
  "webhook_url": "https://hooks.slack.com/services/xxx/yyy/zzz"
}
```

2. When the timer expires, the watcher fires both the email **and** a POST to the webhook URL with the same alert payload.

3. If the webhook delivery fails (network error, bad URL), it is logged as a warning and does not block the email or crash the watcher.

---

## Design Decisions

**Why polling instead of Redis keyspace notifications?**
Keyspace notifications require `notify-keyspace-events` to be enabled on the Redis server, which is disabled by default on managed services like Upstash and AWS ElastiCache. A 1-second polling loop is portable, simple to debug, and negligible in CPU cost.

**Why two Redis keys per monitor?**
The data key (`monitor:{id}`) has no TTL so monitor state — email address, alert count, status — is always readable even after the timer expires. The timer key (`monitor:{id}:timer`) is a tiny sentinel whose sole job is to disappear on schedule. Combining them would delete all context the moment the device goes silent.

**Why Resend over smtplib?**
No SMTP server, credentials, TLS config, or port management. One API key, one function call, and it works on Render and other cloud platforms out of the box.

**Why fakeredis for tests?**
Tests run offline, in CI, and without any credentials. `fakeredis` mirrors the full Redis API including TTL behaviour, so `RedisStore` needs zero changes to work in tests.
