"""うち config — loads from .env"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')

class _Cfg:
    TELEGRAM_TOKEN:  str = os.getenv('TELEGRAM_TOKEN', '')
    ALLOWED_USERS:   set = set(filter(None, os.getenv('ALLOWED_USERS', '').split(',')))
    OLLAMA_URL:      str = os.getenv('OLLAMA_URL', 'http://localhost:11434')
    OLLAMA_MODEL:    str = os.getenv('OLLAMA_MODEL', 'llama3.2')
    VIBEDJ_PORT:     int = int(os.getenv('VIBEDJ_PORT', '6969'))
    VIBEDJ_URL:      str = property(lambda self: f'http://localhost:{self.VIBEDJ_PORT}')

cfg = _Cfg()
