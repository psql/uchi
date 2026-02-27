#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  うち (Uchi) — Smart Home Setup
#  Run from the project directory: cd ~/path/to/uchi && ./install.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────────
R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'
C='\033[0;36m'; M='\033[0;35m'; B='\033[1m'; DIM='\033[2m'; X='\033[0m'

step()  { echo -e "\n${M}${B}▸ $*${X}"; }
ok()    { echo -e "  ${G}✓ $*${X}"; }
warn()  { echo -e "  ${Y}⚠ $*${X}"; }
info()  { echo -e "  ${DIM}$*${X}"; }
fatal() { echo -e "\n${R}${B}✗ $*${X}\n"; exit 1; }
ask()   { echo -e "\n  ${C}${B}?${X} ${B}$*${X}"; }

UCHI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$UCHI_DIR/.env"

# ── Banner ────────────────────────────────────────────────────────────────────
clear
echo
echo -e "${M}${B}"
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║                                              ║"
echo "  ║        うち  Smart Home Installer            ║"
echo "  ║                                              ║"
echo "  ║   Philips Hue  ·  Telegram Bot  ·  Llama    ║"
echo "  ║                                              ║"
echo "  ╚══════════════════════════════════════════════╝"
echo -e "${X}"
echo -e "  ${DIM}Project: $UCHI_DIR${X}"
echo

# ── macOS check ───────────────────────────────────────────────────────────────
step "Checking system"
[[ "$(uname)" == "Darwin" ]] || fatal "うち requires macOS."
ok "macOS $(sw_vers -productVersion)"

# ── Homebrew ──────────────────────────────────────────────────────────────────
step "Homebrew"
if ! command -v brew &>/dev/null; then
  warn "Homebrew not found — installing…"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  # Add brew to PATH for Apple Silicon
  [[ -f /opt/homebrew/bin/brew ]] && eval "$(/opt/homebrew/bin/brew shellenv)"
  ok "Homebrew installed"
else
  ok "Homebrew $(brew --version | head -1 | awk '{print $2}')"
fi

# ── Python ────────────────────────────────────────────────────────────────────
step "Python"
if ! command -v python3 &>/dev/null; then
  warn "Python3 not found — installing…"
  brew install python3
fi
PY="$(command -v python3)"
ok "Python $($PY --version 2>&1 | awk '{print $2}') at $PY"

# ── pip packages ──────────────────────────────────────────────────────────────
step "Installing Python packages"
cd "$UCHI_DIR"
$PY -m pip install -q --user -r requirements.txt
ok "python-telegram-bot, httpx, python-dotenv installed"

# ── Ollama ────────────────────────────────────────────────────────────────────
step "Ollama (local LLM runtime)"
if ! command -v ollama &>/dev/null; then
  warn "Ollama not found — installing…"
  brew install ollama
  ok "Ollama installed"
else
  ok "Ollama $(ollama --version 2>/dev/null | head -1 || echo 'installed')"
fi

# Pull model if not present
if ! ollama list 2>/dev/null | grep -q 'llama3.2'; then
  step "Pulling llama3.2 (this takes a few minutes the first time…)"
  ollama pull llama3.2
  ok "llama3.2 ready"
else
  ok "llama3.2 already present"
fi

# Start Ollama service
if ! brew services list | grep -q 'ollama.*started'; then
  brew services start ollama
  ok "Ollama service started"
else
  ok "Ollama service running"
fi

# ── .env setup ────────────────────────────────────────────────────────────────
step "Configuration"

_env_get() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- || echo ""; }
_env_set() {
  local key="$1" val="$2"
  if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
    # Update existing
    if [[ "$(uname)" == "Darwin" ]]; then
      sed -i '' "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
    else
      sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
    fi
  else
    echo "${key}=${val}" >> "$ENV_FILE"
  fi
}

# Create .env from example if missing
if [[ ! -f "$ENV_FILE" ]]; then
  cp "$UCHI_DIR/.env.example" "$ENV_FILE"
  info "Created .env from .env.example"
fi

# ── Hue bridge discovery ──────────────────────────────────────────────────────
step "Philips Hue Bridge"
HUE_BRIDGE=$(_env_get HUE_BRIDGE)

if [[ -z "$HUE_BRIDGE" || "$HUE_BRIDGE" == "169.254.9.77" ]]; then
  echo -e "  ${DIM}Scanning network for Hue bridge via mDNS (5 seconds)…${X}"
  FOUND_IP=""
  # Try mDNS discovery
  DNS_OUT=$(dns-sd -t 5 -B _hue._tcp local 2>/dev/null || true)
  if echo "$DNS_OUT" | grep -qi "hue"; then
    # Try arp table for common link-local range
    ARP_IPS=$(arp -a 2>/dev/null | grep -Eo '169\.254\.[0-9]+\.[0-9]+' | head -5)
    for ip in $ARP_IPS; do
      if curl -sf --max-time 1 "http://$ip/description.xml" 2>/dev/null | grep -qi "philips"; then
        FOUND_IP="$ip"
        break
      fi
    done
  fi
  if [[ -n "$FOUND_IP" ]]; then
    ok "Found bridge at $FOUND_IP"
    _env_set HUE_BRIDGE "$FOUND_IP"
    HUE_BRIDGE="$FOUND_IP"
  else
    ask "Enter your Hue bridge IP (e.g. 169.254.9.77 or 192.168.1.x):"
    read -r BRIDGE_INPUT
    if [[ -n "$BRIDGE_INPUT" ]]; then
      _env_set HUE_BRIDGE "$BRIDGE_INPUT"
      HUE_BRIDGE="$BRIDGE_INPUT"
    fi
  fi
else
  ok "Bridge: $HUE_BRIDGE (already configured)"
fi

# Source interface
HUE_SRC=$(_env_get HUE_SRC)
if [[ -z "$HUE_SRC" ]]; then
  DETECTED_SRC=$(ipconfig getifaddr en0 2>/dev/null || true)
  if [[ -n "$DETECTED_SRC" ]]; then
    _env_set HUE_SRC "$DETECTED_SRC"
    ok "Ethernet interface (en0): $DETECTED_SRC"
  else
    ask "Enter your Mac's Ethernet (en0) IP for Hue routing:"
    read -r SRC_INPUT
    [[ -n "$SRC_INPUT" ]] && _env_set HUE_SRC "$SRC_INPUT"
  fi
else
  ok "Source interface: $HUE_SRC (already configured)"
fi

# ── Hue API key ───────────────────────────────────────────────────────────────
HUE_API_KEY=$(_env_get HUE_API_KEY)
if [[ -z "$HUE_API_KEY" ]] && [[ -n "$HUE_BRIDGE" ]]; then
  echo
  warn "No Hue API key found."
  echo -e "  ${B}To create one:${X}"
  echo -e "  ${DIM}1. Press the physical button on top of your Hue bridge${X}"
  echo -e "  ${DIM}2. Press Enter here within 30 seconds${X}"
  echo -e "  ${DIM}(or run: curl -X POST http://$HUE_BRIDGE/api -d '{\"devicetype\":\"uchi\"}')${X}"
  ask "Press Enter after pressing the bridge button…"
  read -r
  API_RESP=$(curl -sf -X POST "http://$HUE_BRIDGE/api" \
    -d '{"devicetype":"uchi#macmini"}' 2>/dev/null || echo "")
  NEW_KEY=$(echo "$API_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['success']['username'])" 2>/dev/null || echo "")
  if [[ -n "$NEW_KEY" ]]; then
    _env_set HUE_API_KEY "$NEW_KEY"
    ok "API key obtained and saved"
  else
    warn "Could not get API key automatically."
    ask "Enter your Hue API key (or leave blank to configure later):"
    read -r KEY_INPUT
    [[ -n "$KEY_INPUT" ]] && _env_set HUE_API_KEY "$KEY_INPUT"
  fi
else
  ok "Hue API key: already configured"
fi

# ── Telegram bot token ────────────────────────────────────────────────────────
step "Telegram Bot"
TOKEN=$(_env_get TELEGRAM_TOKEN)
if [[ -z "$TOKEN" || "$TOKEN" == "your-token-here" ]]; then
  echo -e "  ${B}Create your Telegram bot:${X}"
  echo -e "  ${DIM}1. Open Telegram and message @BotFather${X}"
  echo -e "  ${DIM}2. Send: /newbot${X}"
  echo -e "  ${DIM}3. Name it 'Uchi' and choose a username${X}"
  echo -e "  ${DIM}4. Copy the token it gives you${X}"
  echo
  ask "Paste your Telegram bot token (or press Enter to skip for now):"
  read -r TOKEN_INPUT
  if [[ -n "$TOKEN_INPUT" ]]; then
    _env_set TELEGRAM_TOKEN "$TOKEN_INPUT"
    ok "Telegram token saved"
  else
    warn "Skipped — set TELEGRAM_TOKEN in $ENV_FILE later"
  fi
else
  ok "Telegram token already set"
fi

# Allowed users
ALLOWED=$(_env_get ALLOWED_USERS)
if [[ -z "$ALLOWED" ]]; then
  ask "Telegram username(s) to allow (e.g. pasqualedsilva) — blank = open to all:"
  read -r USERS_INPUT
  _env_set ALLOWED_USERS "${USERS_INPUT:-}"
  if [[ -n "$USERS_INPUT" ]]; then
    ok "Allowed users: $USERS_INPUT"
  else
    warn "Open to all users — add ALLOWED_USERS to .env to restrict"
  fi
else
  ok "Allowed users: $ALLOWED"
fi

# ── uchi.local (Bonjour local hostname) ───────────────────────────────────────
step "Local network access (uchi.local)"
CURRENT_HOST=$(scutil --get LocalHostName 2>/dev/null || echo "")
if [[ "$CURRENT_HOST" != "uchi" ]]; then
  ask "Set this Mac's local hostname to 'uchi' so all devices on your network\n  can reach it at ${B}http://uchi.local:6969${X}? (y/N)"
  read -r SET_HOSTNAME
  if [[ "${SET_HOSTNAME,,}" == "y" ]]; then
    sudo scutil --set LocalHostName uchi
    sudo scutil --set HostName uchi
    ok "Hostname set to 'uchi' — accessible at http://uchi.local on your network"
  else
    info "Skipped — you can access via http://$(ipconfig getifaddr en12 2>/dev/null || echo 'YOUR_IP'):$(_env_get VIBEDJ_PORT || echo 6969)"
  fi
else
  ok "Already configured as uchi.local"
fi

# ── LaunchAgents ──────────────────────────────────────────────────────────────
step "Auto-start on login (LaunchAgents)"
AGENTS_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS_DIR"

# VibeDJ server agent
cat > "$AGENTS_DIR/com.uchi.vibedj.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.uchi.vibedj</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>$UCHI_DIR/plugins/vibedj/server.py</string>
    </array>
    <key>WorkingDirectory</key><string>$UCHI_DIR</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$UCHI_DIR/vibedj.log</string>
    <key>StandardErrorPath</key><string>$UCHI_DIR/vibedj.log</string>
</dict>
</plist>
PLIST

# Uchi bot agent
cat > "$AGENTS_DIR/com.uchi.bot.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.uchi.bot</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>$UCHI_DIR/uchi.py</string>
    </array>
    <key>WorkingDirectory</key><string>$UCHI_DIR</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key><false/>
    </dict>
    <key>StandardOutPath</key><string>$UCHI_DIR/uchi.log</string>
    <key>StandardErrorPath</key><string>$UCHI_DIR/uchi.log</string>
</dict>
</plist>
PLIST

ok "LaunchAgent plists written"

# Load / restart services
for label in com.uchi.vibedj com.uchi.bot; do
  # Unload if running (ignore errors)
  launchctl unload "$AGENTS_DIR/${label}.plist" 2>/dev/null || true
  launchctl load "$AGENTS_DIR/${label}.plist"
  ok "${label} loaded"
done

# ── Wait for server ────────────────────────────────────────────────────────────
step "Waiting for VibeDJ to start"
VIBEPORT=$(_env_get VIBEDJ_PORT); VIBEPORT="${VIBEPORT:-6969}"
for i in {1..12}; do
  if curl -sf "http://localhost:$VIBEPORT/api/status" &>/dev/null; then
    ok "VibeDJ is live at http://localhost:$VIBEPORT"
    break
  fi
  sleep 1
  [[ $i -eq 12 ]] && warn "VibeDJ not responding yet — check vibedj.log"
done

# ── Done ──────────────────────────────────────────────────────────────────────
echo
echo -e "${M}${B}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
echo -e "${G}${B}  うち is ready! 🏠✨${X}"
echo -e "${M}${B}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${X}"
echo
echo -e "  ${B}VibeDJ Panel${X}"
echo -e "  ${C}http://localhost:$VIBEPORT${X}  (this machine)"
echo -e "  ${C}http://uchi.local:$VIBEPORT${X}  (any device on your network)"
echo
echo -e "  ${B}Telegram Bot${X}"
TOKEN_CONFIGURED=$(_env_get TELEGRAM_TOKEN)
if [[ -n "$TOKEN_CONFIGURED" && "$TOKEN_CONFIGURED" != "your-token-here" ]]; then
  echo -e "  ${G}✓ Configured — message your bot and say 'lights off'${X}"
else
  echo -e "  ${Y}⚠ Set TELEGRAM_TOKEN in $ENV_FILE then run:${X}"
  echo -e "  ${DIM}launchctl kickstart -k gui/\$UID/com.uchi.bot${X}"
fi
echo
echo -e "  ${B}Logs${X}"
echo -e "  ${DIM}VibeDJ: tail -f $UCHI_DIR/vibedj.log${X}"
echo -e "  ${DIM}Bot:    tail -f $UCHI_DIR/uchi.log${X}"
echo
echo -e "  ${DIM}To re-run setup: ./install.sh${X}"
echo

# Open browser
if [[ -n "$(command -v open 2>/dev/null)" ]]; then
  sleep 1
  open "http://uchi.local:$VIBEPORT" 2>/dev/null || open "http://localhost:$VIBEPORT"
fi
