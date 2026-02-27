"""うち LLM — cache → rules → Ollama, with two-phase refinement"""
import json
import logging
import re

import httpx
from cache import cache
from config import cfg

log = logging.getLogger('uchi.llm')

SYSTEM = """\
You are Uchi (うち), a warm smart-home assistant with a Japanese personality.
You control home devices through plugins.

AVAILABLE ACTIONS
[plugin: vibedj — 照明 lighting]
set_color    params: {color: str, brightness: 0-100}
split_colors params: {colors: [str, str, ...up to 4], brightness?: 0-100}
set_effect   params: {effect: colorCycle|strobe|party|breathe|candle|rainbow|redAlert|wake|sleep, duration?: minutes}
set_preset   params: {preset: relax|romance|chill|arctic|focus|energize|sunset|rave}
set_mode     params: {mode: movie|nightlamp|reading|meditate|focus}
turn_on      params: {brightness?: 0-100}
turn_off     params: {}
blackout     params: {}
fade_in      params: {duration?: seconds}
fade_out     params: {duration?: seconds}
stop_effect  params: {}

RESPONSE FORMAT — valid JSON only, no markdown:
{"plugin":"vibedj","action":"set_color","params":{"color":"purple","brightness":80},"response":"わかった! Purple vibes ✨"}

If it's not a home-control request:
{"plugin":null,"action":"chat","params":{},"response":"friendly reply mixing casual English + Japanese bits"}

EXAMPLES
"lights off"            → {"plugin":"vibedj","action":"turn_off","params":{},"response":"了解! Lights off 🌙"}
"party mode"            → {"plugin":"vibedj","action":"set_effect","params":{"effect":"party"},"response":"パーティー!! 🎉 Let's go!"}
"cozy movie vibes"      → {"plugin":"vibedj","action":"set_mode","params":{"mode":"movie"},"response":"映画タイム！ Movie mode set 🎬"}
"purple please"         → {"plugin":"vibedj","action":"set_color","params":{"color":"purple","brightness":75},"response":"むらさき！ Purple it is ✨"}
"good morning"          → {"plugin":"vibedj","action":"set_effect","params":{"effect":"wake","duration":10},"response":"おはよう！ Sunrise wake-up ☀️"}
"pink and white"        → {"plugin":"vibedj","action":"split_colors","params":{"colors":["pink","white"],"brightness":80},"response":"ピンクと白！ Pink & white ✨"}
"blue and purple vibes" → {"plugin":"vibedj","action":"split_colors","params":{"colors":["blue","purple"],"brightness":75},"response":"青と紫！ Blue & purple ✨"}
"red white and blue"    → {"plugin":"vibedj","action":"split_colors","params":{"colors":["red","white","blue"],"brightness":85},"response":"赤白青！ ✨"}
"""

# ── Known color names ──────────────────────────────────────────────────────────
_COLORS = [
    'red', 'orange', 'yellow', 'lime', 'green', 'teal', 'cyan', 'blue',
    'indigo', 'purple', 'violet', 'pink', 'magenta', 'white', 'warm', 'cool',
    'daylight', 'candle',
]

def _find_colors(t):
    """Return all color names found in text t, in order."""
    return [c for c in _COLORS if c in t]


# ── Public API ─────────────────────────────────────────────────────────────────

def fast_interpret(text):
    """Instant interpretation: cache then rules.
    Returns (result, is_definitive).
      is_definitive=True  → trusted result, skip LLM refinement.
      is_definitive=False → approximate, queue LLM refinement in background.
    """
    hit = cache.get(text)
    if hit:
        return hit, True
    return _rules(text), False


async def llm_interpret(text):
    """Call Ollama, cache the result, return it. Raises on failure."""
    async with httpx.AsyncClient(timeout=12.0) as c:
        r = await c.post(f'{cfg.OLLAMA_URL}/api/chat', json={
            'model':    cfg.OLLAMA_MODEL,
            'messages': [
                {'role': 'system', 'content': SYSTEM},
                {'role': 'user',   'content': text},
            ],
            'stream': False,
            'format': 'json',
        })
        r.raise_for_status()
        result = json.loads(r.json()['message']['content'])
        log.info(f'Ollama → {result}')
        cache.learn(text, result)
        return result


def _differs_meaningfully(fast, refined):
    """True if the LLM result warrants applying a follow-up refinement."""
    if not refined or not refined.get('plugin'):
        return False
    if fast.get('action') != refined.get('action'):
        return True
    fp = fast.get('params', {})
    rp = refined.get('params', {})
    for key in ('color', 'effect', 'preset', 'mode'):
        if fp.get(key) != rp.get(key):
            return True
    # Compare color lists order-insensitively
    if set(fp.get('colors', [])) != set(rp.get('colors', [])):
        return True
    return False


async def interpret(text):
    """Legacy single-call interpret (cache → rules → Ollama)."""
    result, is_definitive = fast_interpret(text)
    if is_definitive or result.get('plugin'):
        return result
    try:
        return await llm_interpret(text)
    except Exception as e:
        log.warning(f'Ollama unavailable ({e}), using rule result')
        return result


# ── Rule-based fallback ────────────────────────────────────────────────────────
def _rules(text):
    t = text.lower()

    def match(*words):
        return any(w in t for w in words)

    # ── Power ─────────────────────────────────────────────────────────────────
    if match('off', 'lights off', 'turn off', 'blackout', 'dark', '消して', 'けして'):
        return _r('turn_off', {}, '了解！ Lights off 🌙')
    if match('turn on', 'lights on', 'all on', 'つけて'):
        return _r('turn_on', {'brightness': 80}, 'はい！ Lights on ✨')

    # ── Compound color phrases (must precede multi-color detection) ───────────
    if 'warm white' in t:
        return _r('set_color', {'color': 'warm', 'brightness': 80}, 'わかった！ Warm white ✨')
    if 'cool white' in t:
        return _r('set_color', {'color': 'cool', 'brightness': 80}, 'わかった！ Cool white ✨')

    # ── Multi-color: "pink and white", "blue and purple", etc. ────────────────
    found = _find_colors(t)
    if len(found) >= 2:
        label = ' + '.join(c.capitalize() for c in found[:4])
        return _r('split_colors', {'colors': found[:4], 'brightness': 80},
                  f'わかった！ {label} ✨')

    # ── Single color ──────────────────────────────────────────────────────────
    for color in _COLORS:
        if color in t:
            return _r('set_color', {'color': color, 'brightness': 80},
                      f'わかった！ {color.capitalize()} ✨')

    # ── Effects ───────────────────────────────────────────────────────────────
    if match('party', 'パーティー'):
        return _r('set_effect', {'effect': 'party'}, 'パーティー！！ 🎉')
    if match('rainbow', '虹'):
        return _r('set_effect', {'effect': 'rainbow'}, '虹色！ Rainbow 🌈')
    if match('breathe', 'pulse', 'breathing'):
        return _r('set_effect', {'effect': 'breathe'}, 'すう…はく… Breathe 🌊')
    if match('candle', 'candlelight', 'flicker', 'ろうそく'):
        return _r('set_effect', {'effect': 'candle'}, 'ろうそく… Candle 🕯')
    if match('strobe', 'flash'):
        return _r('set_effect', {'effect': 'strobe'}, 'ストロボ！ Strobe ⚡')
    if match('alert', 'alarm', '警報'):
        return _r('set_effect', {'effect': 'redAlert'}, '警報！ Red alert 🚨')
    if match('cycle', 'color cycle', 'cycling'):
        return _r('set_effect', {'effect': 'colorCycle'}, '色が変わる～ Color cycling 🌈')
    if match('stop effect', 'no effect', 'normal lighting', '止めて'):
        return _r('stop_effect', {}, '了解！ Effect stopped ⏹')

    # ── Presets ───────────────────────────────────────────────────────────────
    if match('relax', 'relaxing', 'リラックス'):
        return _r('set_preset', {'preset': 'relax'}, 'リラックス～ 🌿')
    if match('romance', 'romantic', 'date night', 'ロマンス'):
        return _r('set_preset', {'preset': 'romance'}, 'ロマンチック！ 🌹')
    if match('sunset', 'dusk', '夕焼け'):
        return _r('set_preset', {'preset': 'sunset'}, '夕焼け色！ Sunset 🌇')
    if match('rave', 'club', 'disco'):
        return _r('set_preset', {'preset': 'rave'}, 'レイブ！ 🎉')
    if match('arctic', 'ice', 'cool blue'):
        return _r('set_preset', {'preset': 'arctic'}, '氷のよう… Arctic 🧊')

    # ── Modes ─────────────────────────────────────────────────────────────────
    if match('movie', 'film', 'cinema', '映画'):
        return _r('set_mode', {'mode': 'movie'}, '映画タイム！ 🎬')
    if match('night lamp', 'nightlight', 'night mode', '夜', 'おやすみ'):
        return _r('set_mode', {'mode': 'nightlamp'}, 'おやすみなさい 🌙')
    if match('read', 'reading', '読書'):
        return _r('set_mode', {'mode': 'reading'}, '読書タイム！ 📖')
    if match('meditate', 'meditation', 'zen', '瞑想'):
        return _r('set_mode', {'mode': 'meditate'}, 'しずか… Zen 🧘')
    if match('focus', 'work', 'study', '集中'):
        return _r('set_mode', {'mode': 'focus'}, '集中！ Focus 💡')

    # ── Fades / timed ─────────────────────────────────────────────────────────
    if match('fade in', 'brighten slowly', 'fade up'):
        return _r('fade_in', {'duration': 5}, 'じわじわ… Fading in ✨')
    if match('fade out', 'dim slowly', 'fade down'):
        return _r('fade_out', {'duration': 5}, 'だんだん… Fading out 🌙')
    if match('wake up', 'sunrise', 'morning', 'おはよう'):
        return _r('set_effect', {'effect': 'wake', 'duration': 10}, 'おはよう！ Sunrise ☀️')
    if match('sleep', 'good night', 'おやすみ'):
        return _r('set_effect', {'effect': 'sleep', 'duration': 20}, 'おやすみ～ Sleep timer 😴')
    if match('bright', 'brighter', 'full brightness', '明るく'):
        return _r('turn_on', {'brightness': 100}, 'はい！ Full brightness ✨')
    if match('dim', 'darker', 'low light', '暗く'):
        return _r('turn_on', {'brightness': 20}, 'はい！ Dimmed 🌙')

    return {'plugin': None, 'action': 'chat', 'params': {},
            'response': 'ごめんなさい… I didn\'t catch that 🤔 Try /help!'}


def _r(action, params, response):
    return {'plugin': 'vibedj', 'action': action, 'params': params, 'response': response}
