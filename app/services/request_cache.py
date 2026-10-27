"""Bounded, process-local cards with lazy expiry, retaining owner checks."""
from collections import OrderedDict
from time import monotonic


class RequestCache:
    def __init__(self, *, ttl=3600, capacity=500, clock=monotonic):
        self.ttl, self.capacity, self.clock = ttl, capacity, clock
        self._items = OrderedDict()

    def _expire(self):
        now = self.clock()
        for key, (deadline, _) in list(self._items.items()):
            if deadline <= now:
                del self._items[key]

    def __setitem__(self, key, value):
        self._expire()
        self._items.pop(key, None)
        self._items[key] = (self.clock() + self.ttl, value)
        while len(self._items) > self.capacity:
            self._items.popitem(last=False)

    def get(self, key, default=None):
        self._expire()
        item = self._items.get(key)
        return default if item is None else item[1]
