#!/usr/bin/env python3
"""VibeDJ – fast Hue controller (HTTP, connection reuse, reachable-only)"""
import json, math, os, random, re, socket, subprocess, threading, time
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, HTTPServer
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import urlparse

# ── Config from .env ──────────────────────────────────────────────────────────
_ENV    = Path(__file__).parent.parent.parent / '.env'
PUBLIC  = Path(__file__).parent / 'public'

def _parse_env(path: Path) -> dict:
    result = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                result[k.strip()] = v.strip()
    return result

_cfg    = _parse_env(_ENV)
BRIDGE  = _cfg.get('HUE_BRIDGE',  '169.254.9.77')
API_KEY = _cfg.get('HUE_API_KEY', 'e7dV5OjJMdehQOk6xoqKoxuccaQUymdJDwrezR2p')
SRC     = (_cfg.get('HUE_SRC', '169.254.234.184'), 0)
PORT    = int(_cfg.get('VIBEDJ_PORT', '6969'))

# ── Settings helpers ──────────────────────────────────────────────────────────
_SETTINGS_KEYS = [
    'HUE_BRIDGE', 'HUE_SRC', 'HUE_API_KEY', 'VIBEDJ_PORT',
    'TELEGRAM_TOKEN', 'ALLOWED_USERS', 'OLLAMA_URL', 'OLLAMA_MODEL',
]
_MASKED_KEYS = {'HUE_API_KEY', 'TELEGRAM_TOKEN'}

def _get_settings() -> dict:
    data = _parse_env(_ENV)
    out  = {}
    for k in _SETTINGS_KEYS:
        v = data.get(k, '')
        if k in _MASKED_KEYS and len(v) > 8:
            out[k] = v[:4] + '·' * 8 + v[-4:]
        else:
            out[k] = v
    return out

def _save_settings(updates: dict):
    """Write updated keys to .env, preserving all other lines."""
    lines     = _ENV.read_text().splitlines() if _ENV.exists() else []
    updated   = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and '=' in stripped:
            k = stripped.split('=', 1)[0].strip()
            if k in updates:
                new_lines.append(f'{k}={updates[k]}')
                updated.add(k)
                continue
        new_lines.append(line)
    for k, v in updates.items():
        if k not in updated:
            new_lines.append(f'{k}={v}')
    _ENV.parent.mkdir(parents=True, exist_ok=True)
    _ENV.write_text('\n'.join(new_lines) + '\n')

# ── Bridge autodiscovery ──────────────────────────────────────────────────────
def _autodiscover_bridge():
    """Discover Hue bridge via mDNS, return (bridge_ip, src_ip) or raise."""

    def _run_dns_sd(args, wait=3):
        p = subprocess.Popen(['dns-sd'] + args,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        time.sleep(wait)
        p.terminate()
        try:    return p.stdout.read()
        except: return ''

    # 1. Browse for _hue._tcp
    out = _run_dns_sd(['-B', '_hue._tcp', 'local'], wait=3)
    m = re.search(r'Add\s+\S+\s+\d+\s+local\.\s+_hue\._tcp\.\s+(.+)', out)
    if not m:
        raise RuntimeError('No Hue bridge found on the network via mDNS')
    name = m.group(1).strip()

    # 2. Lookup service to get hostname
    out = _run_dns_sd(['-L', name, '_hue._tcp', 'local'], wait=3)
    m = re.search(r'can be reached at (\S+?)(?:\.:\d+|\.\s|$)', out)
    if not m:
        raise RuntimeError(f'Could not resolve service "{name}"')
    hostname = m.group(1).rstrip('.')
    if not hostname.endswith('.local'):
        hostname += '.local'

    # 3. Resolve hostname to IP
    out = _run_dns_sd(['-G', 'v4', hostname], wait=3)
    m = re.search(r'\b(\d{1,3}(?:\.\d{1,3}){3})\b', out)
    if not m:
        raise RuntimeError(f'Could not resolve IP for {hostname}')
    bridge_ip = m.group(1)

    # 4. Find a local interface that can reach the bridge
    iface_out = subprocess.check_output(['ifconfig'], text=True)
    link_locals = re.findall(r'inet (169\.254\.\d+\.\d+)', iface_out)
    for src in link_locals:
        try:
            c = HTTPConnection(bridge_ip, 80, timeout=3, source_address=(src, 0))
            c.request('GET', '/api/config')
            c.getresponse().read()
            c.close()
            return bridge_ip, src
        except Exception:
            pass

    raise RuntimeError(f'Bridge at {bridge_ip} but no local interface can reach it '
                       f'(tried: {link_locals})')


def _reload_bridge(bridge_ip, src_ip):
    """Hot-reload BRIDGE/SRC globals and flush all cached connections."""
    global BRIDGE, SRC, _local
    BRIDGE  = bridge_ip
    SRC     = (src_ip, 0)
    _local  = threading.local()          # new object → all threads see no cached conn
    _save_settings({'HUE_BRIDGE': bridge_ip, 'HUE_SRC': src_ip})


# ── Per-thread persistent HTTP connection ─────────────────────────────────────
_local = threading.local()
_pool  = ThreadPoolExecutor(max_workers=24)

# ── Auto-reconnect ─────────────────────────────────────────────────────────────
_reconnect_lock = threading.Lock()
_reconnecting   = False

def _trigger_reconnect():
    global _reconnecting
    with _reconnect_lock:
        if _reconnecting:
            return
        _reconnecting = True
    def _do():
        global _reconnecting
        try:
            bridge_ip, src_ip = _autodiscover_bridge()
            _reload_bridge(bridge_ip, src_ip)
            refresh_lights()
            print(f'[uchi] auto-reconnected: bridge={bridge_ip} src={src_ip} '
                  f'lights={len(_all_ids)} reachable={len(_reachable_ids)}')
        except Exception as e:
            print(f'[uchi] auto-reconnect failed: {e}')
        finally:
            _reconnecting = False
    threading.Thread(target=_do, daemon=True).start()

def _conn():
    if not hasattr(_local, 'c') or _local.c is None:
        _local.c = HTTPConnection(BRIDGE, 80, timeout=4, source_address=SRC)
    return _local.c

def hue(method, path, body=None):
    """One Hue API call, retries once on connection error."""
    for attempt in range(2):
        try:
            c = _conn()
            payload = json.dumps(body).encode() if body is not None else None
            c.request(method, f'/api/{API_KEY}{path}', body=payload,
                      headers={'Content-Type': 'application/json',
                               'Connection': 'keep-alive'})
            r    = c.getresponse()
            data = r.read()
            if r.getheader('Connection', '').lower() == 'close':
                _local.c = None
            try:    return json.loads(data)
            except: return {}
        except Exception:
            _local.c = None
            if attempt == 1:
                _trigger_reconnect()
                return {}

# ── Light cache ───────────────────────────────────────────────────────────────
_cache_lock    = threading.Lock()
_reachable_ids = []
_all_ids       = []
_lights_raw    = {}
_known_ids: set = set()   # lights we've seen since server start

def refresh_lights():
    global _reachable_ids, _all_ids, _lights_raw
    data = hue('GET', '/lights')
    if not isinstance(data, dict): return data
    with _cache_lock:
        _lights_raw    = data
        _all_ids       = list(data.keys())
        _reachable_ids = [i for i, l in data.items() if l['state'].get('reachable')]
    return data

# ── Parallel apply helpers ────────────────────────────────────────────────────
def _par(ids, state):
    if not ids: return
    futures = [_pool.submit(hue, 'PUT', f'/lights/{i}/state', state) for i in ids]
    for f in futures:
        try: f.result(timeout=5)
        except: pass

def apply_reachable(state): _par(_reachable_ids or _all_ids, state)
def apply_ids(ids, state):  _par(ids, state)

# ── Effect engine ─────────────────────────────────────────────────────────────
_state    = {'effect': None, 'bpm': 120, 'sel': None}
_fxstop   = threading.Event()
_fxthread = None

def _target():
    if _state['sel']:
        live = set(_reachable_ids or _all_ids)
        return [i for i in _state['sel'] if i in live] or (_reachable_ids or _all_ids)
    return _reachable_ids or _all_ids

def _tapply(s): _par(_target(), s)

# ── Effect functions ──────────────────────────────────────────────────────────
def fx_colorCycle(stop):
    h = 0
    while not stop.is_set():
        h = (h + 500) % 65535
        _tapply({'on': True, 'hue': h, 'sat': 254, 'bri': 200, 'transitiontime': 3})
        stop.wait(0.35)

def fx_strobe(stop):
    on = True
    while not stop.is_set():
        _tapply({'on': on, 'transitiontime': 0})
        on = not on
        stop.wait(max(0.05, 60 / _state['bpm'] / 2))

def fx_party(stop):
    while not stop.is_set():
        ids = _target()
        fs  = [_pool.submit(hue, 'PUT', f'/lights/{i}/state',
               {'on': True, 'hue': random.randint(0, 65535), 'sat': 254, 'bri': 220,
                'transitiontime': 2}) for i in ids]
        for f in fs:
            try: f.result(timeout=3)
            except: pass
        stop.wait(0.6)

def fx_breathe(stop):
    t = 0
    while not stop.is_set():
        _tapply({'on': True, 'bri': max(8, round(127 + 110 * math.sin(t))),
                 'transitiontime': 2})
        t += 0.18
        stop.wait(0.3)

def fx_candle(stop):
    while not stop.is_set():
        ids = _target()
        fs  = [_pool.submit(hue, 'PUT', f'/lights/{i}/state', {
            'on':  True,
            'hue': 5500 + random.randint(0, 2500),
            'sat': 200  + random.randint(0, 54),
            'bri': 140  + random.randint(0, 90),
            'transitiontime': 3 + random.randint(0, 9),
        }) for i in ids]
        for f in fs:
            try: f.result(timeout=3)
            except: pass
        stop.wait(0.8)

def fx_rainbow(stop):
    offset = 0
    while not stop.is_set():
        ids  = _target()
        step = 65535 // max(len(ids), 1)
        fs   = [_pool.submit(hue, 'PUT', f'/lights/{ids[i]}/state',
                {'on': True, 'hue': (offset + i * step) % 65535, 'sat': 254, 'bri': 200,
                 'transitiontime': 3}) for i in range(len(ids))]
        for f in fs:
            try: f.result(timeout=3)
            except: pass
        offset = (offset + 900) % 65535
        stop.wait(0.4)

def fx_redAlert(stop):
    toggle = True
    while not stop.is_set():
        _tapply({'on': True, 'hue': 0, 'sat': 254,
                 'bri': 254 if toggle else 15, 'transitiontime': 0})
        toggle = not toggle
        stop.wait(max(0.1, 60 / _state['bpm']))

def fx_wake(stop, duration_min=10):
    steps    = 40
    interval = duration_min * 60 / steps
    for i in range(steps):
        if stop.is_set(): break
        t   = i / (steps - 1)
        ct  = round(500 - t * 300)
        bri = round(1 + t * 253)
        _tapply({'on': True, 'ct': max(153, min(500, ct)), 'bri': bri,
                 'transitiontime': round(interval * 9)})
        stop.wait(interval)

def fx_sleep(stop, duration_min=10, start_bri=200):
    steps    = 40
    interval = duration_min * 60 / steps
    for i in range(steps):
        if stop.is_set(): break
        t   = i / (steps - 1)
        bri = max(1, round(start_bri * (1 - t ** 0.7)))
        ct  = round(300 + t * 200)
        _tapply({'on': True, 'ct': max(153, min(500, ct)), 'bri': bri,
                 'transitiontime': round(interval * 9)})
        stop.wait(interval)
    if not stop.is_set():
        time.sleep(1)
        _tapply({'on': False, 'transitiontime': 10})
        _state['effect'] = None

EFFECTS = {
    'colorCycle': fx_colorCycle,
    'strobe':     fx_strobe,
    'party':      fx_party,
    'breathe':    fx_breathe,
    'candle':     fx_candle,
    'rainbow':    fx_rainbow,
    'redAlert':   fx_redAlert,
    'wake':       fx_wake,
    'sleep':      fx_sleep,
}

def stop_fx():
    global _fxthread
    _fxstop.set()
    if _fxthread and _fxthread.is_alive():
        _fxthread.join(timeout=3)
    _fxstop.clear()
    _state['effect'] = None

def start_fx(name, **kwargs):
    global _fxthread
    stop_fx()
    if name in EFFECTS:
        _state['effect'] = name
        _fxthread = threading.Thread(
            target=EFFECTS[name], args=(_fxstop,), kwargs=kwargs, daemon=True)
        _fxthread.start()

# ── Adopt / light celebration ─────────────────────────────────────────────────
def _celebrate_new_light(light_id: str):
    """Rainbow spritz on a newly adopted light, then soft warm-white landing."""
    rainbow_hues = [0, 9362, 18724, 28087, 37449, 46811, 56174, 0]
    for h in rainbow_hues:
        hue('PUT', f'/lights/{light_id}/state',
            {'on': True, 'hue': h, 'sat': 254, 'bri': 220, 'transitiontime': 2})
        time.sleep(0.28)
    # Smooth landing to warm white — client will then apply current vibe
    hue('PUT', f'/lights/{light_id}/state',
        {'on': True, 'ct': 366, 'sat': 0, 'bri': 180, 'transitiontime': 10})

# ── HTTP server ───────────────────────────────────────────────────────────────
MIME = {'.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript',
        '.json': 'application/json', '.ico': 'image/x-icon', '.svg': 'image/svg+xml'}

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads    = True
    address_family    = socket.AF_INET6

    def server_bind(self):
        # IPV6_V6ONLY=0 → dual-stack: accepts both IPv4 and IPv6 connections
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type',                  'application/json')
        self.send_header('Content-Length',                str(len(body)))
        self.send_header('Access-Control-Allow-Origin',   '*')
        self.send_header('Access-Control-Allow-Headers',  'Content-Type')
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        n = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin',  '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        p = urlparse(self.path).path
        try:
            if p == '/api/lights':
                self.send_json(refresh_lights())

            elif p == '/api/groups':
                self.send_json(hue('GET', '/groups'))

            elif p == '/api/status':
                self.send_json({
                    'activeEffect':   _state['effect'],
                    'bpm':            _state['bpm'],
                    'selectedLights': _state['sel'],
                    'reachable':      _reachable_ids,
                })

            elif p == '/api/settings':
                self.send_json(_get_settings())

            elif p == '/api/url':
                ip = _get_network_ip()
                self.send_json({
                    'local':   f'http://localhost:{PORT}',
                    'network': f'http://{ip}:{PORT}',
                    'mdns':    f'http://uchi.local:{PORT}',
                    'ip':      ip,
                    'port':    PORT,
                })

            elif p == '/api/scan/new':
                # Ask Hue for recently-found lights
                new_data = hue('GET', '/lights/new')
                data     = refresh_lights()
                with _cache_lock:
                    current_reachable = set(_reachable_ids)
                    current_all       = set(_all_ids)
                brand_new = []
                if isinstance(new_data, dict):
                    brand_new = [k for k in new_data
                                 if k != 'lastscan' and k in current_all
                                 and k not in _known_ids]
                    _known_ids.update(brand_new)
                self.send_json({
                    'brandNew':       brand_new,
                    'reachable':      list(current_reachable),
                    'lights':         data,
                    'lastScan':       new_data.get('lastscan', '') if isinstance(new_data, dict) else '',
                })

            else:
                fp = PUBLIC / (p.lstrip('/') or 'index.html')
                if fp.exists() and fp.is_file():
                    c = fp.read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type',
                                     MIME.get(fp.suffix.lower(), 'application/octet-stream'))
                    self.send_header('Content-Length', str(len(c)))
                    self.end_headers()
                    self.wfile.write(c)
                else:
                    self.send_json({'error': 'not found'}, 404)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

    def do_PUT(self):
        p    = urlparse(self.path).path
        body = self.read_body()
        try:
            if p == '/api/all/state':
                ids = body.pop('_ids', None)
                if ids:
                    apply_ids(ids, body)
                else:
                    apply_reachable(body)
                self.send_json({'ok': True})
            elif p == '/api/split/state':
                # Distribute colors round-robin across reachable lights
                colors = body.get('colors', [])
                bri    = int(body.get('bri', 200))
                tt     = int(body.get('transitiontime', 30))
                ids    = list(_reachable_ids or _all_ids)
                if ids and colors:
                    futures = [
                        _pool.submit(hue, 'PUT', f'/lights/{ids[i]}/state',
                                     {'on': True, 'bri': bri, 'transitiontime': tt,
                                      **colors[i % len(colors)]})
                        for i in range(len(ids))
                    ]
                    for f in futures:
                        try: f.result(timeout=5)
                        except: pass
                self.send_json({'ok': True})
            elif p.startswith('/api/lights/') and p.endswith('/state'):
                lid = p.split('/')[3]
                self.send_json(hue('PUT', f'/lights/{lid}/state', body))
            elif p.startswith('/api/lights/'):
                # Rename: PUT /api/lights/{id}  body: {"name": "…"}
                parts = p.split('/')
                if len(parts) == 4:
                    lid = parts[3]
                    self.send_json(hue('PUT', f'/lights/{lid}', body))
            else:
                self.send_json({'error': 'not found'}, 404)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

    def do_POST(self):
        p    = urlparse(self.path).path
        body = self.read_body()
        try:
            if p == '/api/effect':
                name   = body.get('name', 'none')
                bpm    = body.get('bpm', 120)
                lights = body.get('lights')
                dur    = float(body.get('duration', 10))
                _state['bpm'] = bpm
                if lights is not None:
                    _state['sel'] = lights or None
                if name == 'none' or name not in EFFECTS:
                    stop_fx()
                elif name in ('wake', 'sleep'):
                    start_fx(name, duration_min=dur)
                else:
                    start_fx(name)
                self.send_json({'ok': True, 'activeEffect': _state['effect']})

            elif p == '/api/scan':
                # Snapshot state before triggering search
                with _cache_lock:
                    prev_all       = list(_all_ids)
                    prev_reachable = list(_reachable_ids)
                # Tell Hue bridge to search for new lights (25-second window)
                hue('POST', '/lights')
                data = refresh_lights()
                _known_ids.update(_all_ids)
                self.send_json({
                    'ok':           True,
                    'scanning':     True,
                    'lights':       data,
                    'scanDuration': 25,
                    'prevIds':      prev_all,
                    'prevReachable': prev_reachable,
                })

            elif p == '/api/scan/celebrate':
                lid = str(body.get('id', ''))
                if lid:
                    threading.Thread(
                        target=_celebrate_new_light, args=(lid,), daemon=True).start()
                self.send_json({'ok': True})

            elif p == '/api/settings':
                # Reject any value that contains our mask sentinel
                updates = {k: v for k, v in body.items()
                           if k in _SETTINGS_KEYS and '·' not in str(v)}
                _save_settings(updates)
                self.send_json({'ok': True, 'restart': True})

            elif p == '/api/reconnect':
                bridge_ip, src_ip = _autodiscover_bridge()
                _reload_bridge(bridge_ip, src_ip)
                refresh_lights()
                self.send_json({
                    'ok':       True,
                    'bridge':   bridge_ip,
                    'src':      src_ip,
                    'lights':   len(_all_ids),
                    'reachable': len(_reachable_ids),
                })

            else:
                self.send_json({'error': 'not found'}, 404)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

def _get_network_ip():
    """Return best outward-facing IP (hotspot > en0 > fallback)."""
    import subprocess
    for iface in ('en12', 'en0', 'en1'):
        try:
            ip = subprocess.check_output(['ipconfig', 'getifaddr', iface],
                                         text=True).strip()
            if ip and not ip.startswith('169.254'):
                return ip
        except Exception:
            pass
    # fallback: en0 link-local is fine for same-machine access
    try:
        return subprocess.check_output(['ipconfig', 'getifaddr', 'en0'], text=True).strip()
    except Exception:
        return 'localhost'


if __name__ == '__main__':
    import subprocess

    ip = _get_network_ip()

    print(f'\n🎧  VibeDJ')
    print(f'    Local  : http://localhost:{PORT}')
    print(f'    Network: http://{ip}:{PORT}')
    print(f'    mDNS   : http://uchi.local:{PORT}')
    print(f'    Bridge : http://{BRIDGE}\n')

    # Register as Bonjour HTTP service so Safari/iOS can discover it
    try:
        subprocess.Popen(
            ['dns-sd', '-R', 'VibeDJ 🏠', '_http._tcp', 'local', str(PORT)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print(f'    Bonjour: VibeDJ._http._tcp.local registered on port {PORT}')
    except Exception as e:
        print(f'    Bonjour: could not register ({e})')

    try:
        refresh_lights()
        _known_ids.update(_all_ids)
        n = len(_all_ids); r = len(_reachable_ids)
        preview = ', '.join(_reachable_ids[:6]) + ('…' if r > 6 else '')
        print(f'    Lights : {n} total, {r} reachable ({preview})\n')
    except Exception as e:
        print(f'    Bridge error: {e}\n')

    server = ThreadedHTTPServer(('::', PORT), Handler)
    print('    Press Ctrl+C to stop.\n')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        stop_fx()
        print('\n👋  Stopped.')
