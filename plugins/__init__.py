"""うち plugin registry"""
from plugins.vibedj import VibeDJPlugin

class _Registry:
    def __init__(self):
        self._p = {}

    def register(self, name: str, plugin):
        self._p[name] = plugin
        return self

    def get(self, name: str):
        return self._p.get(name)

    def all(self):
        return dict(self._p)

registry = _Registry()
registry.register('vibedj', VibeDJPlugin())
