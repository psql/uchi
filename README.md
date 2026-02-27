# うち (Uchi) 🏠

> *うち* — Japanese for "home" / "my place"

A natural-language smart home assistant for Telegram, backed by a local Llama LLM via Ollama. Control lights, set moods, and automate your space — all through casual conversation. Includes a beautiful VibeDJ web control panel.

---

## Quick Install (macOS)

```bash
git clone https://github.com/psql/uchi && cd uchi && ./install.sh
```

The installer will:
- Install Homebrew, Python dependencies, and Ollama (if needed)
- Discover your Philips Hue bridge and get an API key
- Walk you through Telegram bot setup via @BotFather
- Set up auto-start on login via launchd
- Configure `uchi.local` — accessible from any device on your network
- Open VibeDJ in your browser when done

**Requirements:** macOS 12+, Philips Hue bridge on the same network

---

## Architecture

```
Telegram  →  uchi.py  →  llm.py (cache → rules → Ollama)  →  plugins/
                                                               └─ vibedj/  →  Philips Hue
                                                               └─ ...more coming
```

### Resolution order (fastest first)
1. **Cache** — pre-seeded + learned phrases → ~0 ms
2. **Rules** — regex/keyword parser → ~0 ms
3. **Ollama** — local Llama LLM → ~300–800 ms (result cached for next time)

---

## VibeDJ Panel

Access from any device on your network: **`http://uchi.local:6969`**

Features:
- Interactive color wheel (hue + saturation)
- 8 built-in presets, custom preset save/load
- Effects: colorCycle, strobe, party, breathe, candle, rainbow, redAlert, wake, sleep
- Modes: movie, nightlamp, reading, zen, focus, disco
- Fade in/out, sunrise, sunset, blackout
- **✨ Adopt** — scan for new lights with xylophone celebration + rainbow onboarding
- **⚙ Settings** — configure all Hue, Telegram, and Ollama settings from the UI

---

## Manual Setup (step by step)

### 1. Clone and install

```bash
git clone https://github.com/psql/uchi
cd uchi
pip3 install -r requirements.txt --user
```

### 2. Ollama

```bash
brew install ollama
ollama pull llama3.2
brew services start ollama
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env — at minimum set:
#   TELEGRAM_TOKEN   (from @BotFather)
#   HUE_BRIDGE       (your bridge IP, e.g. 192.168.1.x or 169.254.x.x)
#   HUE_API_KEY      (see below)
#   HUE_SRC          (your Mac's Ethernet/WiFi IP that can reach the bridge)
```

**Get a Hue API key:**
```bash
# 1. Press the button on top of your Hue bridge
# 2. Within 30 seconds, run:
curl -X POST http://YOUR_BRIDGE_IP/api -d '{"devicetype":"uchi"}'
# Copy the "username" from the response → that's your API key
```

### 4. Run

```bash
# Terminal 1 — VibeDJ web panel
python3 plugins/vibedj/server.py

# Terminal 2 — Uchi Telegram bot
python3 uchi.py
```

Or load the launch agents for auto-start:
```bash
launchctl load ~/Library/LaunchAgents/com.uchi.vibedj.plist
launchctl load ~/Library/LaunchAgents/com.uchi.bot.plist
```

### 5. uchi.local (optional, recommended)

Make uchi accessible as `http://uchi.local:6969` from any device on your network:
```bash
sudo scutil --set LocalHostName uchi
sudo scutil --set HostName uchi
```
All Apple devices (Mac, iPhone, iPad) on the same WiFi/LAN will resolve `uchi.local` automatically via Bonjour — no DNS setup needed.

---

## Plugins

| Plugin | Description |
|--------|-------------|
| **vibedj** | Philips Hue light control — colors, effects, presets, fades, modes |

More plugins coming: speakers, climate, presence detection…

---

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
| "red alert" | Emergency strobe in red 🚨 |

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_TOKEN` | — | Bot token from @BotFather |
| `ALLOWED_USERS` | *(empty = open)* | Comma-separated Telegram usernames or IDs |
| `HUE_BRIDGE` | `169.254.9.77` | Hue bridge IP address |
| `HUE_API_KEY` | — | Hue API key |
| `HUE_SRC` | `169.254.234.184` | Mac's interface IP used to reach bridge |
| `VIBEDJ_PORT` | `6969` | VibeDJ server port |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint |
| `OLLAMA_MODEL` | `llama3.2` | LLM model to use |

All settings can also be changed from the **⚙ Settings** panel in VibeDJ.

---

## License

MIT
