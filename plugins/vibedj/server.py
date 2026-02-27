#!/usr/bin/env python3
"""VibeDJ – fast Hue controller (HTTP, connection reuse, reachable-only)"""
import json, math, random, threading, time
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, HTTPServer
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import urlparse

BRIDGE  = '169.254.9.77'
API_KEY = 'e7dV5OjJMdehQOk6xoqKoxuccaQUymdJDwrezR2p'
SRC     = ('169.254.234.184', 0)   # bind to en0 so link-local routes correctly
PORT    = 6969
PUBLIC  = Path(__file__).parent / 'public'

# ── Per-thread persistent HTTP connection ─────────────────────────────────────
_local = threading.local()
_pool  = ThreadPoolExecutor(max_workers=24)

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
            r = c.getresponse()
            data = r.read()
            if r.getheader('Connection', '').lower() == 'close':
                _local.c = None
            try:    return json.loads(data)
            except: return {}
        except Exception:
            _local.c = None
            if attempt == 1: return {}

# ── Light cache ───────────────────────────────────────────────────────────────
_cache_lock    = threading.Lock()
_reachable_ids = []
_all_ids       = []
_lights_raw    = {}

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
    """Apply state to a list of light IDs in parallel via thread pool."""
    if not ids: return
    futures = [_pool.submit(hue, 'PUT', f'/lights/{i}/state', state) for i in ids]
    for f in futures:
        try: f.result(timeout=5)
        except: pass

def apply_reachable(state): _par(_reachable_ids or _all_ids, state)
def apply_ids(ids, state):  _par(ids, state)

# ── Effect engine ─────────────────────────────────────────────────────────────
_state = {'effect': None, 'bpm': 120, 'sel': None}
_fxstop  = threading.Event()
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
        fs = [_pool.submit(hue, 'PUT', f'/lights/{i}/state',
              {'on': True, 'hue': random.randint(0, 65535), 'sat': 254, 'bri': 220, 'transitiontime': 2})
              for i in ids]
        for f in fs:
            try: f.result(timeout=3)
            except: pass
        stop.wait(0.6)

def fx_breathe(stop):
    t = 0
    while not stop.is_set():
        _tapply({'on': True, 'bri': max(8, round(127 + 110 * math.sin(t))), 'transitiontime': 2})
        t += 0.18
        stop.wait(0.3)

def fx_candle(stop):
    while not stop.is_set():
        ids = _target()
        fs = [_pool.submit(hue, 'PUT', f'/lights/{i}/state', {
            'on': True,
            'hue': 5500 + random.randint(0, 2500),
            'sat': 200 + random.randint(0, 54),
            'bri': 140 + random.randint(0, 90),
            'transitiontime': 3 + random.randint(0, 9)
        }) for i in ids]
        for f in fs:
            try: f.result(timeout=3)
            except: pass
        stop.wait(0.8)

def fx_rainbow(stop):
    offset = 0
    while not stop.is_set():
        ids = _target()
        step = 65535 // max(len(ids), 1)
        fs = [_pool.submit(hue, 'PUT', f'/lights/{ids[i]}/state',
              {'on': True, 'hue': (offset + i * step) % 65535, 'sat': 254, 'bri': 200, 'transitiontime': 3})
              for i in range(len(ids))]
        for f in fs:
            try: f.result(timeout=3)
            except: pass
        offset = (offset + 900) % 65535
        stop.wait(0.4)

def fx_redAlert(stop):
    toggle = True
    while not stop.is_set():
        _tapply({'on': True, 'hue': 0, 'sat': 254, 'bri': 254 if toggle else 15, 'transitiontime': 0})
        toggle = not toggle
        stop.wait(max(0.1, 60 / _state['bpm']))

def fx_wake(stop, duration_min=10):
    """Dim warm → bright cool white over duration_min minutes (like sunrise alarm)."""
    steps = 40
    interval = duration_min * 60 / steps
    for i in range(steps):
        if stop.is_set(): break
        t   = i / (steps - 1)
        ct  = round(500 - t * 300)          # 500K (candle) → 200K (daylight)
        bri = round(1 + t * 253)             # 1 → 254
        _tapply({'on': True, 'ct': max(153, min(500, ct)), 'bri': bri,
                 'transitiontime': round(interval * 9)})
        stop.wait(interval)

def fx_sleep(stop, duration_min=10, start_bri=200):
    """Current → warm dim → off over duration_min minutes."""
    steps = 40
    interval = duration_min * 60 / steps
    for i in range(steps):
        if stop.is_set(): break
        t   = i / (steps - 1)
        bri = max(1, round(start_bri * (1 - t ** 0.7)))  # eases out
        ct  = round(300 + t * 200)                         # cooler → warmer
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

# ── HTTP server (threaded) ────────────────────────────────────────────────────
MIME = {'.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript',
        '.json': 'application/json', '.ico': 'image/x-icon', '.svg': 'image/svg+xml'}

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        n = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(n)) if n else {}

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
            else:
                fp = PUBLIC / (p.lstrip('/') or 'index.html')
                if fp.exists() and fp.is_file():
                    c = fp.read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', MIME.get(fp.suffix.lower(), 'application/octet-stream'))
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
            elif p.startswith('/api/lights/') and p.endswith('/state'):
                lid = p.split('/')[3]
                self.send_json(hue('PUT', f'/lights/{lid}/state', body))
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
                bpm    = body.get('bpm',  120)
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
            else:
                self.send_json({'error': 'not found'}, 404)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

if __name__ == '__main__':
    import subprocess
    try:
        ip = subprocess.check_output(['ipconfig', 'getifaddr', 'en1'], text=True).strip()
    except Exception:
        ip = 'check ifconfig'

    print(f'\n🎧  VibeDJ')
    print(f'    Local  : http://localhost:{PORT}')
    print(f'    Network: http://{ip}:{PORT}  ← open on any device')
    print(f'    Bridge : http://{BRIDGE}\n')

    try:
        refresh_lights()
        print(f'    Lights : {len(_all_ids)} total, {len(_reachable_ids)} reachable ({", ".join(_reachable_ids[:6])}{"…" if len(_reachable_ids)>6 else ""})\n')
    except Exception as e:
        print(f'    Bridge error: {e}\n')

    server = ThreadedHTTPServer(('0.0.0.0', PORT), Handler)
    print('    Press Ctrl+C to stop.\n')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        stop_fx()
        print('\n👋  Stopped.')
