import os
import logging

log = logging.getLogger("jobs.providers")
_REGISTRY = {}

def register(cls):
    _REGISTRY[cls.name] = cls
    return cls

def get_providers():
    """Instantiate providers that are enabled (JOB_PROVIDERS env) AND configured."""
    from . import adzuna  # noqa: F401  (importing registers it)
    # To add a source: create providers/<name>.py with @register, then import it above.
    enabled = [s.strip() for s in os.getenv("JOB_PROVIDERS", "adzuna").split(",") if s.strip()]
    out = []
    for name in enabled:
        cls = _REGISTRY.get(name)
        if not cls:
            log.warning("Unknown provider %s", name)
            continue
        p = cls()
        if p.is_configured():
            out.append(p)
        else:
            log.warning("Provider %s enabled but not configured", name)
    return out