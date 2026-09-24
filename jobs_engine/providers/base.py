from abc import ABC, abstractmethod
from typing import Optional
from jobs_engine.normalize import NormalizedJob


class JobProvider(ABC):
    """Contract every job source implements. The aggregator only talks to this interface."""
    name: str = ""    # stable id stored in DB, e.g. "adzuna"
    label: str = ""   # shown on job cards, e.g. "Adzuna"

    @abstractmethod
    def is_configured(self) -> bool:
        """True if required env vars / keys exist."""

    @abstractmethod
    def fetch(self, query: str, location: str = "", page: int = 1) -> list:
        """Call the external API and return raw dicts. May raise; the aggregator logs it."""

    @abstractmethod
    def normalize(self, raw: dict) -> Optional[NormalizedJob]:
        """Convert one raw record into the common schema (or None to skip)."""