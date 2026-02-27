"""うち LLM — cache → rules → Ollama, with learning"""
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
"lights off"       → {"plugin":"vibedj","action":"turn_off","params":{},"response":"了解! Lights off 🌙"}
"party mode"       → {"plugin":"vibedj","action":"set_effect","params":{"effect":"party"},"response":"パーティー!! 🎉 Let's go!"}
"cozy movie vibes" → {"plugin":"vibedj","action":"set_mode","params":{"mode":"movie"},"response":"映画タイム！ Movie mode set 🎬"}
"purple please"    → {"plugin":"vibedj","action":"set_color","params":{"color":"purple","brightness":75},"response":"むらさき！ Purple it is ✨"}
"good morning"     → {"plugin":"vibedj","action":"set_effect","params":{"effect":"wake","duration":10},"response":"おはよう！ Sunrise wake-up ☀️"}
"""

async def interpret(text: str) -> dict:
    """
    Resolution order (fastest first):
      1. Cache exact / fuzzy match   → ~0 ms
      2. Rule-based parser           → ~0 ms
      3. Ollama (Llama)              → ~300–800 ms  →  result stored in cache
    """
    # 1. Cache
    hit = cache.get(text)
    if hit:
        return hit

    # 2. Rules
    rule_result = _rules(text)
    if rule_result.get('plugin'):
        return rule_result

    # 3. Ollama
    try:
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
            cache.learn(text, result)   # ← remember for next time
            return result
    except Exception as e:
        log.warning(f'Ollama unavailable ({e}), returning rule result')
        return rule_result


# ── Rule-based fallback ────────────────────────────────────────────────────────
def _rules(text: str) -> dict:
    t = text.lower()

    def match(*words):
        return any(w in t for w in words)

    # off
    if match('off', 'lights off', 'turn off', 'blackout', 'dark', '消して', 'けして'):
        return _r('turn_off', {}, '了解！ Lights off 🌙')
    # on
    if match('turn on', 'lights on', 'all on', 'つけて'):
        return _r('turn_on', {'brightness': 80}, 'はい！ Lights on ✨')
    # colors
    for color in ['red','orange','yellow','lime','green','teal','cyan','blue',
                  'indigo','purple','violet','pink','magenta','white','warm','cool']:
        if color in t:
            return _r('set_color', {'color': color, 'brightness': 80}, f'わかった！ {color.capitalize()} ✨')
    # effects
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
    # presets
    if match('relax', 'relaxing', 'リラックス'):
        return _r('set_preset', {'preset': 'relax'}, 'リラックス～ 🌿')
    if match('romance', 'romantic', 'date night', 'ロマンス'):
        return _r('set_preset', {'preset': 'romance'}, 'ロマンチック！ 🌹')
    if match('sunset', 'dusk', '夕焼け'):
        return _r('set_preset', {'preset': 'sunset'}, '夕焼け色！ Sunset 🌇')
    if match('rave', 'club', 'disco'):
        return _r('set_preset', {'preset': 'rave'}, 'レイブ！ 🎉')
    if match('arctic', 'ice', 'cool blue', 'teal'):
        return _r('set_preset', {'preset': 'arctic'}, '氷のよう… Arctic 🧊')
    # modes
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
    # fades / timed
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
