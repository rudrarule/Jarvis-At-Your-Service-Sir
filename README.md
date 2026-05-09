<p align="center">
  <img src="https://img.shields.io/badge/J.A.R.V.I.S-v0.3.0-00d4ff?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiMwMGQ0ZmYiIHN0cm9rZS13aWR0aD0iMiI+PGNpcmNsZSBjeD0iMTIiIGN5PSIxMiIgcj0iMTAiLz48cGF0aCBkPSJNMTIgMnYyMCIvPjxwYXRoIGQ9Ik0yIDEyaDIwIi8+PC9zdmc+" alt="J.A.R.V.I.S"/>
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&logoColor=black" alt="React"/>
  <img src="https://img.shields.io/badge/FastAPI-0.110+-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/Ollama-Local_LLM-white?style=for-the-badge" alt="Ollama"/>
  <img src="https://img.shields.io/badge/AWS_Bedrock-Llama_4-FF9900?style=for-the-badge&logo=amazonaws&logoColor=white" alt="AWS Bedrock"/>
</p>

<h1 align="center">🤖 J.A.R.V.I.S. — Just A Rather Very Intelligent System</h1>

<p align="center">
  <strong>A full-stack, voice-activated AI assistant that controls your OS, remembers who you are, sees your screen, and messages people on WhatsApp — all from a single wake word.</strong>
</p>

<p align="center">
  <em>Not a chatbot. Not a GPT wrapper. A real digital butler.</em>
</p>

---

## ⚡ What Can J.A.R.V.I.S. Do?

```
"Hey Jarvis, open Chrome and Spotify"         → 0ms regex, both apps launch in parallel
"Hey Jarvis, what's on my screen?"             → Screenshot → Llama 4 Maverick vision analysis
"Hey Jarvis, message Mom that I'll be late"    → Contact resolution → Draft → Confirm → Send via WhatsApp
"Hey Jarvis, play Lose My Mind"                → YouTube playback, instant
"Hey Jarvis, search for latest AI papers"      → Playwright browser opens with DuckDuckGo results
"Hey Jarvis, lock the system"                  → Workstation locked immediately
"Hey Jarvis, what's the weather in New York?"  → Real-time weather data
"Hey Jarvis, read my notes.txt"                → File system access with path validation
```

---

## 🧠 Architecture

### 3-Tier Hybrid LLM Pipeline

Every user command flows through an intelligent routing system that minimizes latency and cost:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        User Input                                   │
│                    "open chrome and spotify"                         │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                  ┌────────▼────────┐
                  │   Tier 1: Regex │  ← 0ms latency
                  │   Fast-Path     │    Compound command splitting
                  │   (21 patterns) │    Parallel sub-command execution
                  └───────┬─────────┘
                          │ miss
                  ┌───────▼─────────┐
                  │  Tier 2: Ollama │  ← <5s, 100% local
                  │  Qwen 2.5 3B   │    Chat shortcut (no tool schemas)
                  │  (Chat Mode)    │    Conversational responses
                  └───────┬─────────┘
                          │ complex query
                  ┌───────▼─────────┐
                  │  Tier 3: AWS    │  ← 6-10s, cloud
                  │  Bedrock        │    Full tool schemas
                  │  Llama 4        │    Multi-step reasoning
                  │  Maverick 17B   │    Auto-fallback to Ollama
                  └─────────────────┘
```

**Key design decisions:**
- **Selective schema loading** — Intent classifier maps commands to tool groups, so the LLM only sees 2-3 relevant tool schemas instead of all 21
- **Compound command splitting** — `"open Chrome and Spotify"` is parsed into parallel sub-commands via regex before hitting any LLM
- **Automatic fallback** — If Bedrock is unreachable, Tier 3 gracefully degrades to local Ollama with full tool schemas
- **Response caching** — Conversational replies are cached in-memory; tool-action responses are excluded to prevent stale results

---

### 🎙️ Voice Pipeline — On-Device Neural Wake Word

Zero cloud dependency. Wake word detection runs entirely in-browser via **ONNX Runtime (WASM)**:

```
Microphone → AudioWorklet (80ms chunks @ 16kHz)
  → Silero VAD (voice activity detection)
    → Mel Spectrogram (5 frames × 32 features)
      → Embedding Model (76 frames → 96-dim vector)
        → "Hey Jarvis" Keyword Head (score > 0.5 → activate)
```

| Feature | Implementation |
|---|---|
| Wake Word Engine | OpenWakeWord ONNX models (browser WASM) |
| One-Breath Commands | `"Hey Jarvis, play Lose My Mind"` — inline detection |
| Foreground Command | Browser `webkitSpeechRecognition` (low latency) |
| Background Command | Mic → WAV encode → Backend `/stt` → Faster-Whisper |
| Text-to-Speech | Edge-TTS with FallbackVoiceManager + VoiceQueue |
| Startup Sequence | Stark Protocol — briefing + music offer + VS Code |

---

### 🛠️ Tool Orchestration — 21 Native Tools

Native function calling with JSON schemas. Tools are grouped by intent for selective loading:

| Group | Tools | Description |
|---|---|---|
| 🎵 **Music** | `play_music` | YouTube playback via voice command |
| 🌐 **Browser** | `browser_search`, `open_url` | Playwright-powered DuckDuckGo search + direct URL navigation |
| 💻 **App Control** | `open_app`, `close_app`, `list_running_apps` | Whitelisted app launcher (Chrome, VS Code, Spotify, Netflix, Discord, etc.) + UWP/Store app support |
| 📁 **File System** | `read_file`, `write_file`, `append_file`, `list_directory`, `search_files`, `search_in_files` | Sandboxed workspace file operations |
| 🔒 **System** | `lock_system`, `shutdown_system`, `restart_system` | Confirmation-gated destructive actions |
| 📂 **Folders** | `open_folder` | Safe directory access (Desktop, Downloads, Documents, etc.) |
| 🌤️ **Weather** | `get_weather` | Real-time weather data |
| 📱 **WhatsApp** | `whatsapp_briefing`, `whatsapp_unread`, `whatsapp_missed_calls`, `whatsapp_send` | Full messaging via Baileys connector |
| 👁️ **Vision** | Retina Module (integrated) | Screenshot → PII safety gate → Llama 4 Maverick multimodal reasoning |

---

### 👁️ Retina Vision Module

Screen understanding powered by **Llama 4 Maverick 17B** via AWS Bedrock Converse API:

```
Intent Detection (keyword + scope check)
  → PII Safety Gate (blocks password managers, banking, login screens)
    → Active Window Capture (pyautogui + pygetwindow)
      → Resize to 1024×1024 → JPEG compression
        → Base64 encode → Bedrock Converse (multimodal)
          → Jarvis-style spoken analysis
```

- **Debounce guard** — 15s cooldown between vision triggers
- **Graceful degradation** — Falls back to text-only LLM if vision fails

---

### 🧬 Memory — ChromaDB RAG

Jarvis remembers. Important messages are stored as vector embeddings and retrieved via semantic search:

- **Auto-detection** — Regex patterns identify memorable info (`"my name is..."`, `"I work at..."`, `"remember this..."`)
- **Duplicate prevention** — Cosine similarity > 0.92 = skip storage
- **Capacity management** — 500-entry limit with automatic oldest-entry eviction
- **Context injection** — Retrieved memories are injected into the LLM prompt at inference time

---

### 📱 WhatsApp Integration

Dual-channel WhatsApp support:

| Channel | Technology | Use Case |
|---|---|---|
| **Baileys Connector** | Node.js WebSocket bridge | Unread messages, missed calls, outbound messaging, contact resolution |
| **Twilio Webhook** | HTTP POST `/whatsapp` | Inbound message handling with busy-mode auto-response |

**Outbound messaging workflow:**
```
"Message Mom that I'll be late"
  → Regex extract (contact: "Mom", intent: "I'll be late")
    → Contact resolution (fuzzy match against contact index)
      → LLM drafts natural message
        → User confirmation prompt
          → Send via Baileys
```

---

## 📁 Project Structure

```
holo-core-nexus/
├── backend/                    # Python FastAPI server
│   ├── main.py                 # API endpoints (chat, tts, whatsapp, stark-protocol, stt)
│   ├── services/
│   │   ├── llm_service.py      # 3-Tier Hybrid Brain (870 lines)
│   │   ├── memory_service.py   # ChromaDB RAG memory
│   │   ├── vision_service.py   # Retina Module (screen capture + PII gate)
│   │   ├── text_to_speech_service.py  # Edge-TTS with voice queue
│   │   ├── session_service.py  # Per-user conversation history
│   │   ├── embedding_service.py # Vector embedding generation
│   │   ├── contact_resolver.py  # Fuzzy contact matching for WhatsApp
│   │   ├── whatsapp_service.py  # Twilio WhatsApp adapter
│   │   ├── whatsapp_baileys_service.py # Baileys connector bridge
│   │   └── whatsapp_formatter.py # Message formatting
│   ├── tools/
│   │   ├── registry.py         # Central tool registry (21 tools, schema groups)
│   │   ├── browser_tool.py     # Playwright web search + URL opener
│   │   ├── music_tool.py       # YouTube playback
│   │   ├── system_control_tool.py # OS control (whitelisted + gated)
│   │   ├── file_system_tool.py # Sandboxed file operations
│   │   ├── weather_tool.py     # Weather data
│   │   └── whatsapp_tool.py    # WhatsApp tool wrappers
│   ├── workflows/
│   │   └── wa_send_workflow.py # Multi-step outbound WA messaging
│   ├── jarvis/                 # TTS engine, voice queue, fallback manager
│   ├── db/                     # ChromaDB client
│   └── models/                 # Pydantic request/response models
│
├── frontend/                   # React + TypeScript + Vite
│   ├── src/
│   │   ├── hooks/
│   │   │   ├── useJarvisWake.ts   # Master voice controller + Stark Protocol
│   │   │   └── useWakeWord.ts     # ONNX wake word detection (669 lines)
│   │   └── ...
│   └── public/
│       └── openwakeword/       # ONNX models (mel, embedding, VAD, hey_jarvis)
│
└── whatsapp-connector/         # Node.js Baileys WhatsApp bridge
```

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.11+**
- **Node.js 18+**
- **Ollama** with `qwen2.5:3b` model pulled
- **AWS credentials** configured (for Bedrock — optional, falls back to local)

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Pull the local LLM model
ollama pull qwen2.5:3b

# Configure environment
cp .env.example .env
# Edit .env with your API keys (AWS, Twilio, etc.)

# Start the backend (port 8080)
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start dev server (port 8082)
npm run dev
```

### WhatsApp Connector (Optional)

```bash
cd whatsapp-connector
npm install
node src/index.js
# Scan QR code on first run
```

---

## ⚙️ Environment Variables

Create a `.env` file in the `backend/` directory:

```env
# LLM Configuration
USE_MODEL=true                          # Enable Bedrock routing
AWS_BEDROCK_REGION=""
_MODEL_ID=""
MODEL_MAX_TOKENS=1024

# WhatsApp (Twilio)
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886

# WhatsApp (Baileys Connector)
WA_CONNECTOR_URL=http://localhost:3001

# Allowed WhatsApp users
ALLOWED_WHATSAPP_USERS=whatsapp:+91XXXXXXXXXX
```

---

## 🗺️ Roadmap

- [x] 3-Tier Hybrid LLM Pipeline (Regex → Ollama → Bedrock)
- [x] On-device ONNX wake word detection
- [x] 21 native tools with selective schema loading
- [x] ChromaDB RAG memory with deduplication
- [x] Retina Vision Module (Llama 4 Maverick multimodal)
- [x] WhatsApp integration (Baileys + Twilio)
- [x] Edge-TTS with voice queue and fallback manager
- [x] Compound command splitting with parallel execution
- [x] Background-tab audio capture via Faster-Whisper STT
- [x] Stark Protocol bootup sequence
- [ ] **LangGraph migration** — Stateful agentic workflows with conditional branching, human-in-the-loop confirmations, persistent state, and self-correcting retry loops
- [ ] Multi-agent delegation (specialized sub-agents for research, coding, scheduling)
- [ ] Calendar & email integration
- [ ] Proactive notifications and ambient awareness

---

## 🛡️ Security

- **Whitelisted applications** — Only pre-approved apps can be launched
- **Confirmation-gated destructive actions** — Shutdown/restart require explicit `confirm=True`
- **PII safety gate** — Vision module blocks capture when password managers or banking apps are detected
- **Sandboxed file access** — File system tools operate within a defined workspace
- **WhatsApp user allowlist** — Only authorized phone numbers can interact via WhatsApp

---

## 📜 License

This project is for personal use and learning purposes.


### 🧠 Future(LangGraph Migration — Toward Fully Agentic Workflows)

The current orchestration layer is event-driven and request/response based.

The next evolution of J.A.R.V.I.S. is migrating toward **LangGraph-powered stateful agentic workflows** capable of reasoning across long-running tasks, adapting dynamically to context, and recovering from failures autonomously.

Planned capabilities include:

* **Persistent workflow state** — Maintain execution context across sessions and interruptions
* **Conditional reasoning & branching** — Dynamically choose execution paths based on real-world context
* **Parallel tool orchestration** — Execute independent tools concurrently for lower latency
* **Dependency-aware execution graphs** — Multi-step planning with ordered task dependencies
* **Self-correcting retry loops** — Detect tool failures and autonomously retry or reroute execution
* **Human-in-the-loop confirmations** — Safety-gated approval for destructive or high-impact actions
* **Multi-agent delegation** — Specialized sub-agents for research, coding, scheduling, and system operations

This transition enables workflows such as:

```text
"Hey Jarvis, prepare my coding environment"

→ Check current time
→ Open VS Code + project workspace
→ Resume preferred coding playlist
→ Check unread WhatsApp messages
→ Summarize latest AI news
→ Detect pending Git tasks
→ Continue previous workflow state

or to book a ticket of movie From District
→ Search nearby theatres and available showtimes
→ Detect preferred theatre and seating preferences from memory
→ Compare ticket pricing across providers → Suggest best timing based on calendar availability
→ Open booking page automatically
→ Select seats intelligently
→ Ask for payment confirmation
→ Complete booking workflow → Save booking details into memory
→ Draft WhatsApp messages for friends/family
→ Add event to calendar automatically
```

Future LangGraph orchestration will allow Jarvis to move beyond reactive command execution into:

* long-running reasoning,
* adaptive planning,
* contextual decision making,
* and autonomous multi-step task coordination.

The long-term vision is to transform J.A.R.V.I.S. from an assistant into a continuously reasoning local-first AI operating layer.


---

<p align="center">
  <em>"Will that be all, sir?"</em>
  <br/>
  <strong>— J.A.R.V.I.S.</strong>
</p>
