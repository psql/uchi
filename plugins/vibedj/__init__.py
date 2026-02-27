"""うち › vibedj plugin — Philips Hue light control"""
import asyncio
import logging

import httpx
from config import cfg

log = logging.getLogger('uchi.vibedj')

FADE = 30   # 3 seconds (Hue transitiontime units = 100 ms each)

# ── Color table (name → Hue API params) ──────────────────────────────────────
COLORS = {
    'red':      {'hue': 0,     'sat': 254},
    'orange':   {'hue': 6554,  'sat': 254},
    'yellow':   {'hue': 12288, 'sat': 254},
    'lime':     {'hue': 21845, 'sat': 254},
    'green':    {'hue': 25600, 'sat': 254},
    'teal':     {'hue': 32768, 'sat': 254},
    'cyan':     {'hue': 34952, 'sat': 254},
    'blue':     {'hue': 46920, 'sat': 254},
    'indigo':   {'hue': 49344, 'sat': 254},
    'purple':   {'hue': 51000, 'sat': 254},
    'violet':   {'hue': 53000, 'sat': 254},
    'pink':     {'hue': 60000, 'sat': 254},
    'magenta':  {'hue': 56850, 'sat': 254},
    'white':    {'sat': 0, 'ct': 300},
    'warm':     {'sat': 0, 'ct': 450},
    'cool':     {'sat': 0, 'ct': 200},
    'daylight': {'sat': 0, 'ct': 156},
    'candle':   {'sat': 0, 'ct': 500},
}

PRESETS = {
    'relax':    {'on': True, 'hue': 8378,  'sat': 144, 'bri': 150, 'transitiontime': FADE},
    'romance':  {'on': True, 'hue': 63000, 'sat': 220, 'bri': 100, 'transitiontime': FADE},
    'chill':    {'on': True, 'hue': 45000, 'sat': 220, 'bri': 120, 'transitiontime': FADE},
    'arctic':   {'on': True, 'hue': 33620, 'sat': 220, 'bri': 200, 'transitiontime': FADE},
    'focus':    {'on': True, 'ct': 233,             'bri': 219, 'transitiontime': FADE},
    'energize': {'on': True, 'ct': 153,             'bri': 254, 'transitiontime': FADE},
    'sunset':   {'on': True, 'hue': 3640,  'sat': 254, 'bri': 180, 'transitiontime': FADE},
    'rave':     {'on': True, 'hue': 55000, 'sat': 254, 'bri': 254, 'transitiontime': FADE},
}

MODES = {
    'movie':     {'on': True, 'ct': 400, 'bri': 45,  'transitiontime': FADE},
    'nightlamp': {'on': True, 'ct': 500, 'bri': 6,   'transitiontime': FADE},
    'reading':   {'on': True, 'ct': 300, 'bri': 230, 'transitiontime': FADE},
    'meditate':  {'on': True, 'hue': 44000, 'sat': 180, 'bri': 60, 'transitiontime': FADE},
    'focus':     {'on': True, 'ct': 233, 'bri': 220, 'transitiontime': FADE},
}


class VibeDJPlugin:
    """Executes light-control intents against the VibeDJ server."""

    @property
    def _url(self):
        return f'http://localhost:{cfg.VIBEDJ_PORT}'

    async def execute(self, action: str, params: dict):
        handler = getattr(self, f'_do_{action}', None)
        if handler:
            try:
                return await handler(params)
            except Exception as e:
                log.error(f'vibedj action {action} failed: {e}')
                return {'error': str(e)}
        log.warning(f'Unknown vibedj action: {action}')
        return {}

    # ── HTTP helpers ──────────────────────────────────────────────────────────
    async def _put(self, path, data):
        async with httpx.AsyncClient(timeout=6.0) as c:
            r = await c.put(f'{self._url}{path}', json=data)
            return r.json()

    async def _post(self, path, data):
        async with httpx.AsyncClient(timeout=6.0) as c:
            r = await c.post(f'{self._url}{path}', json=data)
            return r.json()

    # ── Action handlers ───────────────────────────────────────────────────────
    async def _do_set_color(self, p):
        color = p.get('color', 'white').lower()
        bri   = round(int(p.get('brightness', 80)) / 100 * 254)
        c     = COLORS.get(color, COLORS['white'])
        return await self._put('/api/all/state', {'on': True, 'bri': bri, 'transitiontime': FADE, **c})

    async def _do_set_effect(self, p):
        return await self._post('/api/effect', {
            'name':     p.get('effect'),
            'bpm':      int(p.get('bpm', 120)),
            'duration': float(p.get('duration', 10)),
        })

    async def _do_set_preset(self, p):
        state = PRESETS.get(p.get('preset', 'relax'), PRESETS['relax'])
        return await self._put('/api/all/state', state)

    async def _do_set_mode(self, p):
        state = MODES.get(p.get('mode', 'reading'), MODES['reading'])
        return await self._put('/api/all/state', state)

    async def _do_turn_on(self, p):
        bri = round(int(p.get('brightness', 80)) / 100 * 254)
        return await self._put('/api/all/state', {'on': True, 'bri': bri, 'transitiontime': FADE})

    async def _do_turn_off(self, _p):
        return await self._put('/api/all/state', {'on': False, 'transitiontime': 0})

    async def _do_blackout(self, _p):
        return await self._put('/api/all/state', {'on': False, 'transitiontime': 0})

    async def _do_fade_in(self, p):
        dur = int(p.get('duration', 5))
        await self._put('/api/all/state', {'on': True, 'bri': 1, 'transitiontime': 0})
        await asyncio.sleep(0.4)
        return await self._put('/api/all/state', {'on': True, 'bri': 200, 'transitiontime': dur * 10})

    async def _do_fade_out(self, p):
        dur = int(p.get('duration', 5))
        return await self._put('/api/all/state', {'bri': 1, 'transitiontime': dur * 10})

    async def _do_stop_effect(self, _p):
        return await self._post('/api/effect', {'name': 'none'})
