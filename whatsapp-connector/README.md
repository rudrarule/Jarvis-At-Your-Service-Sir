# J.A.R.V.I.S WhatsApp Connector

Self-hosted WhatsApp connector for the Jarvis AI assistant system, built with [Baileys](https://github.com/WhiskeySockets/Baileys).

## Architecture

```
WhatsApp (your phone)
       ↕
Baileys Socket (Node.js)
       ↕
Event Handlers (messages, calls)
       ↕
In-Memory Store + SQLite Rate Limiter
       ↕
Express REST API (:3100)
       ↕
Jarvis FastAPI Backend (:8082)
```

## Features

- **QR Pairing** — Scan once, persistent auth state
- **Unread Messages** — Event-driven tracking, no polling
- **Missed Calls** — Detection + auto-reply with rate limiting
- **REST API** — Clean endpoints for Jarvis integration
- **Reconnect** — Exponential backoff, auth corruption recovery
- **Stealth** — Doesn't mark you as online

## Quick Start

### 1. Install Dependencies

```bash
cd whatsapp-connector
npm install
```

### 2. Configure

Copy `.env.example` to `.env` and fill in your approved contacts:

```bash
cp .env.example .env
```

Edit `.env`:
```ini
APPROVED_CONTACTS=919876543210,919123456789
```

### 3. Start the Connector

```bash
npm start
```

A QR code will appear in the terminal. **Scan it with WhatsApp** (Settings → Linked Devices → Link a Device).

After pairing, the auth state is saved to `auth_state/`. You won't need to scan again unless you log out.

### 4. Verify

```bash
curl http://localhost:3100/health
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Connector health + connection status |
| `GET` | `/unread-summary` | Unread messages grouped by chat |
| `GET` | `/missed-calls` | Recent missed call events |
| `POST` | `/send-message` | Send a WhatsApp message |
| `GET` | `/connection` | Current connection state |
| `POST` | `/clear-unread` | Clear unread messages |
| `POST` | `/clear-calls` | Clear missed call records |
| `GET` | `/auto-replies` | View auto-reply rate-limit records |

### Example: Unread Summary

```bash
curl http://localhost:3100/unread-summary
```

```json
{
  "total_chats": 3,
  "total_messages": 12,
  "chats": [
    {
      "chat_id": "919876543210@s.whatsapp.net",
      "chat_name": "Mom",
      "unread_count": 4,
      "last_message": "Call me when you're free",
      "timestamp": 1714123456000,
      "messages": [...]
    }
  ]
}
```

### Example: Send Message

```bash
curl -X POST http://localhost:3100/send-message \
  -H "Content-Type: application/json" \
  -d '{"chat_id": "919876543210", "text": "Hello from Jarvis!"}'
```

## Auto-Reply Rules

When a missed call is detected:

1. ✅ Must be from an **approved contact** (configured in `.env`)
2. ✅ Must be a **personal chat** (not a group)
3. ✅ Must not have received an auto-reply within **12 hours** (configurable)
4. ❌ Never replies to unknown numbers
5. ❌ Never replies to groups
6. ❌ Never sends duplicate replies

Rate limiting is backed by SQLite for persistence across restarts.

## Jarvis Integration

The FastAPI backend calls this connector via:

```
GET  http://localhost:8082/wa/unread       → Unread messages
GET  http://localhost:8082/wa/missed-calls → Missed calls
GET  http://localhost:8082/wa/briefing     → Full briefing text
POST http://localhost:8082/wa/send         → Send a message
```

### Example Jarvis Flow

```
User: "Jarvis, who messaged me today?"
  → Jarvis calls GET /wa/briefing
  → Gets raw data: "3 unread messages from Mom, Dad, Boss..."
  → LLM summarizes naturally: "Sir, you have messages from your mother,
    father, and your boss. Your mother asked you to call her back."
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| QR won't scan | Delete `auth_state/` folder and restart |
| Disconnects frequently | Check internet connection; Baileys will auto-reconnect |
| Auth corrupted | The connector auto-detects and wipes corrupted auth |
| No missed call events | WhatsApp Web has limited call event support; some calls may not trigger events |
| Empty unread results | Messages are only tracked from the moment the connector starts |
| `better-sqlite3` build fails | Install build tools: `npm install -g windows-build-tools` |

## File Structure

```
whatsapp-connector/
├── index.js           # Main entry point
├── package.json
├── .env               # Configuration
├── .env.example
├── .gitignore
└── src/
    ├── config.js      # Environment config loader
    ├── auth.js        # Persistent auth state management
    ├── store.js       # In-memory message & call store
    ├── db.js          # SQLite rate-limit store
    ├── events.js      # Baileys event handlers
    └── api.js         # Express REST API
```
