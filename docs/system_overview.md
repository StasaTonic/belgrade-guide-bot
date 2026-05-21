# System Overview

## Project Description
A Telegram AI bot that helps groups of friends in Belgrade reach consensus on where to go — solving the group decision problem by collecting each person's preferences, deal-breakers, and must-haves through natural conversation, then recommending the single best event or venue that works for everyone (a Pareto-optimal compromise). The bot uses Google Gemini, a multi-source event database, Google Places API, and OpenStreetMap to find real Belgrade venues and events.

## Core Features

### 1. Telegram Bot Integration
- Built using `python-telegram-bot` library
- Supports commands:
  - `/start`: Greets the user
  - `/help`: Displays usage instructions
- Handles text messages and Telegram location shares
- Works in both **private chats** and **group/channel chats**

### 2. AI-Powered Conversation (ReAct Agent)
- Uses Google Gemini (`gemini-2.5-flash` by default, configurable in `src/configs/prod.yml`)
- Implements a ReAct (Reason + Act) agent loop via LangGraph:
  - `agent_node`: calls the LLM with bound tools
  - `ToolNode`: executes tool calls returned by the LLM
  - Loop continues until the LLM produces a final text response
- Collects through natural conversation:
  - Individual interests, must-haves, and deal-breakers per user
  - Budget in RSD (optional)
- In group chats, messages are prefixed with `@username` so the LLM can attribute preferences per participant and reason about the group as a whole
- Applies deal-breaker-first logic: options that violate any member's hard constraints are eliminated before must-haves are considered

### 3. LangChain Tools
Five tools are registered with the model via `bind_tools`:

| Tool | Input | Output |
|------|-------|--------|
| `find_telegram_event` | `query`, `constraints` | Formatted event from local Telegram dataset |
| `find_concerts` | `query` | Concert details and ticket link from concerts dataset |
| `find_restaurants` | `query` | Restaurant details and reservation link from Ontopo dataset |
| `find_venue` | `query` | HTML link to venue via Google Places API |
| `find_venue_osm` | `amenity_type` | List of venues from OpenStreetMap |

Tools are defined in `src/tools.py` using LangChain's `@tool` decorator. The agent always tries `find_telegram_event` first, then falls back to specialised tools (`find_concerts`, `find_restaurants`) or venue tools (`find_venue`, `find_venue_osm`) depending on the query.

### 4. Message Persistence (SQLite)
- All messages stored in SQLite via `aiosqlite` (path configured in `src/configs/prod.yml`)
- Schema: `chat_id`, `username`, `channel`, `role`, `message_text`, `timestamp`
- `channel` column distinguishes messages from different Telegram groups/channels
- Full conversation history is loaded per `chat_id` and reconstructed as LangChain message objects on each request, enabling the agent to track all group members' preferences across the conversation
- No LangGraph checkpointer — history is managed entirely via SQLite

### 5. Location Sharing
- Users can share their Telegram location directly
- Bot reverse-geocodes coordinates to city/country via Google Places API
- Synthesizes a text input (`"I'm in City, Country"`) to feed the agent

### 6. Observability (Arize Phoenix + OpenTelemetry)
- Traces sent to Arize Phoenix via OTLP
- `register(auto_instrument=True)` automatically activates `LangChainInstrumentor`
- Captured spans:
  - `CHAIN` — full `graph.invoke()` execution
  - `LLM` — each Gemini model call
  - `TOOL` — each tool execution (`find_telegram_event`, `find_venue`, etc.)
- Phoenix runs as a Docker service; endpoint configured via `PHOENIX_COLLECTOR_ENDPOINT`

## Architecture

### Components
| File | Responsibility |
|------|----------------|
| `src/app.py` | Telegram bot handlers, routing private vs group messages |
| `src/ai_agent.py` | LangGraph ReAct agent, `dialog_router()` entry point |
| `src/tools.py` | LangChain `@tool` definitions, BM25 search engine, data loading |
| `src/prompts.py` | System prompt defining private/group flows, tool priority, and consensus logic |
| `src/db.py` | SQLite message storage and retrieval |
| `src/config.py` | YAML config loader (`MODEL_NAME`, `BOT_USERNAME`, `DB_PATH`) |
| `src/google_api.py` | Google Places API and OpenStreetMap API integrations |
| `src/configs/prod.yml` | Production configuration (DB path, bot username, model name) |
| `scripts/chat.py` | Console testing interface |
| `scripts/db_history.py` | Print message history from SQLite |

### Key Dependencies
- `python-telegram-bot`: Telegram API
- `langchain-google-genai`: Gemini model via LangChain
- `langchain`, `langchain-core`: LLM framework and tools
- `langgraph<1.0.0`: ReAct graph orchestration
- `aiosqlite`: Async SQLite for message persistence
- `requests`: HTTP calls to Google Places and OpenStreetMap APIs
- `numpy`: Random candidate selection in venue search
- `openinference-instrumentation-langchain`: LangChain auto-instrumentation for Phoenix
- `arize-phoenix-otel`: Phoenix OTLP registration

### Environment Variables
| Variable | Purpose |
|----------|---------|
| `TG_BOT_TOKEN` | Telegram bot token |
| `GEMINI_API_KEY` | Google Gemini API key |
| `GOOGLE_API_KEY` | Google Places API key |
| `PHOENIX_COLLECTOR_ENDPOINT` | Phoenix OTLP endpoint (default: `http://phoenix:6006`) |
| `ENV` | Config environment (`prod`) |
| `DATA_DIR` | SQLite data directory inside container |

### Deployment
- Docker-based: `Dockerfile` for the bot, `docker-compose.yml` for Phoenix
- `make build` — builds the bot image
- `make run` — starts Phoenix + bot container (joined to Phoenix network)
- `make chat` — starts Phoenix + interactive console session
- `make eval` — runs the evaluation suite inside Docker
- `make phoenix` — starts only the Phoenix observability service

## Usage Flow
1. User sends a message to the bot in a private or group chat
2. Bot loads full chat history from SQLite and reconstructs message context
3. In group chats, each message is prefixed with `@username` so the LLM tracks who said what
4. LangGraph agent runs:
   - LLM collects preferences from all group members, identifying deal-breakers and must-haves
   - Once enough preferences are collected, the LLM calls tools in priority order:
     1. `find_telegram_event` — searches local Telegram event dataset via BM25
     2. `find_concerts` or `find_restaurants` — if the query is specific to concerts or dining
     3. `find_venue` — Google Places fallback for general venue search
     4. `find_venue_osm` — OpenStreetMap fallback if Google Places is unavailable
   - LLM formats the final answer, explaining why the suggestion fits the group
5. Bot replies with text or HTML (venue/event link)
6. Both user message and bot reply are saved to SQLite
7. Full trace (LLM calls + tool calls) sent to Phoenix