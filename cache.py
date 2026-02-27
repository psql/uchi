"""うち command cache — pre-seeded, learns from every Ollama call, fuzzy-matches."""
import json
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path

log = logging.getLogger('uchi.cache')
CACHE_FILE = Path.home() / '.uchi' / 'cache.json'

# ── Seed helpers ──────────────────────────────────────────────────────────────
def _v(action, params, response=None):
    return {'plugin': 'vibedj', 'action': action, 'params': params,
            'response': response or _auto_response(action, params)}

def _c(color, bri=80):
    return _v('set_color', {'color': color, 'brightness': bri},
              f'わかった！ {color.capitalize()} ✨')

def _e(effect, **kw):
    EMOJI = {'party':'🎉','rainbow':'🌈','breathe':'🌊','candle':'🕯',
             'strobe':'⚡','redAlert':'🚨','colorCycle':'🌈',
             'wake':'☀️','sleep':'😴'}
    label = effect.replace('Alert','').replace('Cycle','')
    return _v('set_effect', {'effect': effect, **kw},
              f'はい！ {label.capitalize()} {EMOJI.get(effect,"✨")}')

def _p(preset):
    EMOJI = {'relax':'🌿','romance':'🌹','chill':'💜','arctic':'🧊',
             'focus':'💡','energize':'⚡','sunset':'🌇','rave':'🎉'}
    return _v('set_preset', {'preset': preset},
              f'{preset.capitalize()} {EMOJI.get(preset,"✨")}')

def _m(mode):
    EMOJI = {'movie':'🎬','nightlamp':'🌙','reading':'📖','meditate':'🧘','focus':'💡'}
    return _v('set_mode', {'mode': mode},
              f'映画タイム！' if mode == 'movie' else f'{mode.capitalize()} mode {EMOJI.get(mode,"✨")}')

def _auto_response(action, params):
    if action == 'turn_off':  return '了解！ Lights off 🌙'
    if action == 'turn_on':   return 'はい！ Lights on ✨'
    if action == 'blackout':  return '真っ暗！ Blackout ◼'
    if action == 'fade_in':   return 'じわじわ… Fading in ✨'
    if action == 'fade_out':  return 'だんだん… Fading out 🌙'
    if action == 'stop_effect': return '了解！ Effect stopped ⏹'
    return 'わかった！ ✨'

# ── Pre-seeded phrases ────────────────────────────────────────────────────────
SEED: dict = {
    # power
    'lights off':       _v('turn_off', {}),
    'off':              _v('turn_off', {}),
    'turn off':         _v('turn_off', {}),
    'kill the lights':  _v('turn_off', {}),
    'lights out':       _v('turn_off', {}),
    'turn off lights':  _v('turn_off', {}),
    'blackout':         _v('blackout', {}),
    'lights on':        _v('turn_on', {'brightness': 80}),
    'on':               _v('turn_on', {'brightness': 80}),
    'turn on':          _v('turn_on', {'brightness': 80}),
    'all on':           _v('turn_on', {'brightness': 80}),
    'full brightness':  _v('turn_on', {'brightness': 100}),
    'brighten':         _v('turn_on', {'brightness': 100}),
    'dim':              _v('turn_on', {'brightness': 20}),
    'dim lights':       _v('turn_on', {'brightness': 20}),
    # colors
    'red':      _c('red'),   'red lights':    _c('red'),
    'orange':   _c('orange'),'orange lights': _c('orange'),
    'yellow':   _c('yellow'),'yellow lights': _c('yellow'),
    'green':    _c('green'), 'green lights':  _c('green'),
    'blue':     _c('blue'),  'blue lights':   _c('blue'),
    'purple':   _c('purple'),'purple lights': _c('purple'),
    'pink':     _c('pink'),  'pink lights':   _c('pink'),
    'white':    _c('white'), 'warm white':    _c('warm'),
    'warm':     _c('warm'),  'cool white':    _c('cool'),
    'cool':     _c('cool'),  'cyan':          _c('cyan'),
    'teal':     _c('teal'),  'magenta':       _c('magenta'),
    'make it red':    _c('red'),
    'make it blue':   _c('blue'),
    'make it purple': _c('purple'),
    'make it green':  _c('green'),
    'make it pink':   _c('pink'),
    # effects
    'party':            _e('party'),
    'party mode':       _e('party'),
    'party time':       _e('party'),
    'lets party':       _e('party'),
    "let's party":      _e('party'),
    'rainbow':          _e('rainbow'),
    'rainbow mode':     _e('rainbow'),
    'breathe':          _e('breathe'),
    'breathing':        _e('breathe'),
    'pulse':            _e('breathe'),
    'pulsing':          _e('breathe'),
    'candle':           _e('candle'),
    'candlelight':      _e('candle'),
    'firelight':        _e('candle'),
    'strobe':           _e('strobe'),
    'strobe lights':    _e('strobe'),
    'alert':            _e('redAlert'),
    'red alert':        _e('redAlert'),
    'alarm':            _e('redAlert'),
    'color cycle':      _e('colorCycle'),
    'colour cycle':     _e('colorCycle'),
    'cycle':            _e('colorCycle'),
    'cycling':          _e('colorCycle'),
    'stop':             _v('stop_effect', {}),
    'stop effect':      _v('stop_effect', {}),
    'no effect':        _v('stop_effect', {}),
    'cancel effect':    _v('stop_effect', {}),
    'normal':           _v('stop_effect', {}),
    'wake up':          _e('wake',  duration=10),
    'wake':             _e('wake',  duration=10),
    'sunrise':          _e('wake',  duration=10),
    'good morning':     _e('wake',  duration=10),
    'morning':          _e('wake',  duration=10),
    'おはよう':          _e('wake',  duration=10),
    'sleep':            _e('sleep', duration=20),
    'sleep mode':       _e('sleep', duration=20),
    'good night':       _e('sleep', duration=20),
    'goodnight':        _e('sleep', duration=20),
    'おやすみ':          _e('sleep', duration=20),
    # presets
    'relax':    _p('relax'),  'relaxing':  _p('relax'),
    'romance':  _p('romance'),'romantic':  _p('romance'),
    'date night':_p('romance'),
    'chill':    _p('chill'),
    'arctic':   _p('arctic'), 'ice':       _p('arctic'),
    'focus':    _m('focus'),  'work mode': _m('focus'),
    'energize': _p('energize'),
    'sunset':   _p('sunset'),
    'rave':     _p('rave'),
    # modes
    'movie':          _m('movie'),  'movie mode':   _m('movie'),
    'movie time':     _m('movie'),  'cinema':       _m('movie'),
    'film mode':      _m('movie'),
    'night':          _m('nightlamp'), 'nightlight': _m('nightlamp'),
    'night mode':     _m('nightlamp'), 'night lamp': _m('nightlamp'),
    'reading':        _m('reading'),   'read':       _m('reading'),
    'reading mode':   _m('reading'),
    'zen':            _m('meditate'),  'meditate':   _m('meditate'),
    'meditation':     _m('meditate'),
    # fades
    'fade in':        _v('fade_in',  {'duration': 3}),
    'fade up':        _v('fade_in',  {'duration': 3}),
    'fade out':       _v('fade_out', {'duration': 3}),
    'fade down':      _v('fade_out', {'duration': 3}),
    'dim slowly':     _v('fade_out', {'duration': 5}),
    'brighten slowly':_v('fade_in',  {'duration': 5}),
}


# ── Cache class ───────────────────────────────────────────────────────────────
class CommandCache:
    def __init__(self):
        self._data: dict = dict(SEED)   # start with pre-seeded phrases
        self._load()

    def _load(self):
        if CACHE_FILE.exists():
            try:
                learned = json.loads(CACHE_FILE.read_text())
                self._data.update(learned)
                log.info(f'Cache loaded: {len(self._data)} entries '
                         f'({len(learned)} learned + {len(SEED)} seed)')
            except Exception as e:
                log.warning(f'Cache load failed: {e}')
        else:
            log.info(f'Cache initialised with {len(SEED)} seed entries')

    def save(self):
        """Persist only the *learned* entries (not the seed — they're in code)."""
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        learned = {k: v for k, v in self._data.items() if k not in SEED}
        CACHE_FILE.write_text(json.dumps(learned, indent=2))

    @staticmethod
    def _norm(text: str) -> str:
        """Lowercase, strip punctuation, collapse whitespace."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s\u3000-\u9fff]", ' ', text)  # keep CJK
        return re.sub(r'\s+', ' ', text).strip()

    def get(self, text: str) -> dict | None:
        """
        Look up text in three passes:
          1. Exact match after normalisation     → instant
          2. Sequence similarity ≥ 0.88          → instant
          3. Jaccard word-overlap ≥ 0.72         → instant
        Returns None if nothing matches (caller falls through to LLM).
        """
        norm = self._norm(text)

        # Pass 1 — exact
        if norm in self._data:
            log.debug(f'Cache HIT (exact): "{norm}"')
            return self._data[norm]

        # Pass 2 — sequence similarity
        best_seq, best_key = 0.0, None
        for key in self._data:
            s = SequenceMatcher(None, norm, key).ratio()
            if s > best_seq:
                best_seq, best_key = s, key

        if best_seq >= 0.88:
            log.debug(f'Cache HIT (seq {best_seq:.2f}): "{norm}" ≈ "{best_key}"')
            return self._data[best_key]

        # Pass 3 — Jaccard word overlap
        norm_words = set(norm.split())
        best_jac, best_jkey = 0.0, None
        for key in self._data:
            key_words = set(key.split())
            union = norm_words | key_words
            if union:
                j = len(norm_words & key_words) / len(union)
                if j > best_jac:
                    best_jac, best_jkey = j, key

        if best_jac >= 0.72:
            log.debug(f'Cache HIT (jac {best_jac:.2f}): "{norm}" ≈ "{best_jkey}"')
            return self._data[best_jkey]

        log.debug(f'Cache MISS: "{norm}" (best seq={best_seq:.2f}, jac={best_jac:.2f})')
        return None

    def learn(self, text: str, intent: dict):
        """Store a new phrase→intent mapping and persist it."""
        norm = self._norm(text)
        if norm and intent.get('plugin'):   # only cache actionable intents
            self._data[norm] = intent
            self.save()
            log.debug(f'Cache LEARN: "{norm}"')


cache = CommandCache()
