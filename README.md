# うち (Uchi) 🏠

> *うち* — Japanese for "home" / "my place"

A natural-language smart home bot for Telegram, backed by a local Llama LLM via Ollama. Control lights, set moods, and automate your space — all through casual conversation.

## Architecture

```
Telegram  →  uchi.py  →  llm.py (Ollama/Llama)  →  plugins/
                                                       └─ vibedj/  →  Philips Hue
```

## Plugins

| Plugin | Description |
|--------|-------------|
| **vibedj** | Philips Hue light control — colors, effects, presets, fades, modes |

More plugins coming: speakers, climate, presence detection…

## Quick start

### 1. Install dependencies

```bash
# Python packages
pip3 install -r requirements.txt

# Ollama (local LLM runtime)
brew install ollama
ollama pull llama3.2
ollama serve &   # or: brew services start ollama
```

### 2. Create your Telegram bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. `/newbot` → name it **Uchi** → username `uchi_home_bot` (or similar)
3. Copy the token

### 3. Configure

```bash
cp .env.example .env
# Edit .env — set TELEGRAM_TOKEN (and optionally ALLOWED_USERS)
```

### 4. Run

```bash
# Terminal 1 — VibeDJ web panel (http://localhost:6969)
python3 plugins/vibedj/server.py

# Terminal 2 — Uchi bot
python3 uchi.py
```

Or use the launch agents (see below) to run both automatically on login.

## Launch agents (auto-start on login)

```bash
# Load both daemons
launchctl load ~/Library/LaunchAgents/com.uchi.vibedj.plist
launchctl load ~/Library/LaunchAgents/com.uchi.bot.plist
```

## Example conversations

| You say | Uchi does |
|---------|-----------|
| "lights off" | 了解！ Lights off 🌙 |
| "purple" | Sets all lights to purple ✨ |
| "movie time" | Dim amber cinema mode 🎬 |
| "party mode" | Starts the party effect 🎉 |
| "good morning" | 10-min sunrise wake-up ☀️ |
| "fade out over 30 seconds" | Slowly dims lights out |
| "relax" | Warm orange relaxing preset 🌿 |

## License

MIT
