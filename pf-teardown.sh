#!/bin/bash
# ── uchi port-80 teardown ─────────────────────────────────────────────────────
# Removes proxy daemon and any leftover pf rules.
# Run: sudo bash ~/uchi/pf-teardown.sh
# ─────────────────────────────────────────────────────────────────────────────

if [ "$EUID" -ne 0 ]; then
  echo "❌  Please run with sudo:  sudo bash ~/uchi/pf-teardown.sh"
  exit 1
fi

# Stop and remove proxy LaunchDaemon
PLIST="/Library/LaunchDaemons/home.uchi.proxy.plist"
if [ -f "$PLIST" ]; then
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  echo "✅  proxy daemon removed"
fi

# Remove proxy script
rm -f /usr/local/lib/uchi-proxy.py
echo "✅  proxy script removed"

# Clear any leftover pf uchi anchor
if pfctl -a uchi -F all 2>/dev/null; then
  echo "✅  pf uchi anchor cleared"
fi

# Restore pf.conf if we touched it
if [ -f /etc/pf.conf.uchi.bak ]; then
  cp /etc/pf.conf.uchi.bak /etc/pf.conf
  pfctl -f /etc/pf.conf 2>/dev/null || true
  echo "✅  /etc/pf.conf restored"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  teardown complete — http://uchi.local:6969 still works"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
