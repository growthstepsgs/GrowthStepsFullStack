"""Adzuna official API (https://developer.adzuna.com). Free key; India = country "in"."""
import os
import httpx
from jobs_engine.normalize import (NormalizedJob, extract_experience, extract_skills,
                                   infer_work_mode, parse_dt)
from .base import JobProvider
from .registry import register


@register
class AdzunaProvider(JobProvider):
    name = "adzuna"
    label = "Adzuna"
    BASE = "https://api.adzuna.com/v1/api/jobs"

    def __init__(self):
        self.app_id = os.getenv("ADZUNA_APP_ID", "")
        self.app_key = os.getenv("ADZUNA_APP_KEY", "")
        self.country = os.getenv("ADZUNA_COUNTRY", "in")

    def is_configured(self):
        return bool(self.app_id and self.app_key)

    def fetch(self, query, location="", page=1):
        params = {"app_id": self.app_id, "app_key": self.app_key,
                  "results_per_page": 20, "what": query, "content-type": "application/json"}
        if location:
            params["where"] = location
        r = httpx.get(f"{self.BASE}/{self.country}/search/{page}", params=params, timeout=8)
        r.raise_for_status()
        return r.json().get("results", [])

    def normalize(self, raw):
        title = (raw.get("title") or "").strip()
        desc = raw.get("description") or ""
        location = (raw.get("location") or {}).get("display_name")
        exp_min, exp_max = extract_experience(f"{title} {desc}")
        return NormalizedJob(
            source=self.name,
            source_job_id=str(raw.get("id", "")),
            url=raw.get("redirect_url", ""),
            title=title,
            company=((raw.get("company") or {}).get("display_name") or "").strip(),
            location=location,
            work_mode=infer_work_mode(title, desc, location),
            exp_min=exp_min, exp_max=exp_max,
            salary_min=int(raw["salary_min"]) if raw.get("salary_min") else None,
            salary_max=int(raw["salary_max"]) if raw.get("salary_max") else None,
            salary_currency="INR" if self.country == "in" else None,
            skills=extract_skills(f"{title} {desc}"),
            description=desc,
            posted_at=parse_dt(raw.get("created")),
        )