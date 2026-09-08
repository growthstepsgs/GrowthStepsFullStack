import time
from threading import Lock

class SimpleCache:
    """
    Lightweight, thread-safe in-memory cache for serverless environments.
    Data persists across warm container invocations.
    """
    def __init__(self):
        self._cache = {}
        self._lock = Lock()

    def get(self, key):
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.time() > expires_at:
                del self._cache[key]
                return None
            return value

    def set(self, key, value, ttl=300):
        with self._lock:
            self._cache[key] = (value, time.time() + ttl)

    def delete(self, key):
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()

cache = SimpleCache()
