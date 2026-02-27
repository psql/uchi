#!/bin/bash
# ── uchi port-80 setup ────────────────────────────────────────────────────────
# Forwards port 80 → 6969 via a tiny Python proxy running as root.
# Run once: sudo bash ~/uchi/pf-setup.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e

if [ "$EUID" -ne 0 ]; then
  echo "❌  Please run with sudo:  sudo bash ~/uchi/pf-setup.sh"
  exit 1
fi

PROXY_SRC="$(cd "$(dirname "$0")" && pwd)/uchi-proxy.py"
PROXY_DST="/usr/local/lib/uchi-proxy.py"
PLIST="/Library/LaunchDaemons/home.uchi.proxy.plist"

# 1. Copy proxy script
cp "$PROXY_SRC" "$PROXY_DST"
chmod 755 "$PROXY_DST"
echo "✅  proxy script → $PROXY_DST"

# 2. Write LaunchDaemon plist
cat > "$PLIST" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>            <string>home.uchi.proxy</string>
  <key>RunAtLoad</key>        <true/>
  <key>KeepAlive</key>        <true/>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/usr/local/lib/uchi-proxy.py</string>
  </array>
  <key>StandardOutPath</key>  <string>/tmp/uchi-proxy.log</string>
  <key>StandardErrorPath</key><string>/tmp/uchi-proxy.log</string>
</dict>
</plist>
PLIST
echo "✅  LaunchDaemon → $PLIST"

# 3. Load (unload first in case it's already running)
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load   "$PLIST"
sleep 1

# 4. Quick test
if curl -s --max-time 2 http://localhost/ -o /dev/null; then
  echo "✅  port 80 → 6969 active"
else
  echo "⚠️  proxy started but port 80 test failed — check /tmp/uchi-proxy.log"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  http://uchi.local  works in all browsers"
echo "  (port 80 → 6969, auto-restarts on reboot)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
