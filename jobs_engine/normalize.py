"""Shared helpers every provider uses to convert messy external data into the common schema."""
import hashlib
import ipaddress
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

SKILL_VOCAB = [
    "python", "django", "flask", "fastapi", "sql", "postgresql", "mysql", "mongodb",
    "javascript", "typescript", "react", "node.js", "angular", "vue", "html", "css",
    "java", "spring", "c++", "c#", ".net", "go", "rust", "php", "laravel", "ruby",
    "aws", "azure", "gcp", "docker", "kubernetes", "git", "linux", "rest api",
    "machine learning", "deep learning", "nlp", "pandas", "numpy", "tensorflow",
    "pytorch", "power bi", "tableau", "excel", "data analysis", "figma", "selenium",
    "android", "kotlin", "swift", "flutter", "react native", "devops", "ci/cd",
    "generative ai", "llm", "prompt engineering", "langchain", "supabase", "firebase",
]


@dataclass
class NormalizedJob:
    source: str
    source_job_id: str
    url: str
    title: str
    company: str
    location: Optional[str] = None
    work_mode: Optional[str] = None          # remote | hybrid | onsite
    exp_min: Optional[int] = None
    exp_max: Optional[int] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: Optional[str] = None
    skills: list = field(default_factory=list)
    description: Optional[str] = None
    posted_at: Optional[datetime] = None

    @property
    def dedupe_key(self) -> str:
        return make_dedupe_key(self.title, self.company, self.location)


_COMPANY_NOISE = re.compile(
    r"\b(pvt|private|ltd|limited|inc|llc|corp|corporation|co|technologies|technology|solutions)\b")

def _clean(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())
    return re.sub(r"\s+", " ", s).strip()

def make_dedupe_key(title, company, location) -> str:
    """Same role + same company + same city => same job, regardless of platform."""
    company_n = re.sub(r"\s+", " ", _COMPANY_NOISE.sub(" ", _clean(company))).strip()
    city = _clean((location or "").split(",")[0])
    raw = f"{_clean(title)}|{company_n}|{city}"
    return hashlib.sha1(raw.encode()).hexdigest()

def infer_work_mode(*texts) -> Optional[str]:
    t = " ".join(x for x in texts if x).lower()
    if "hybrid" in t:
        return "hybrid"
    if re.search(r"\b(remote|work from home|wfh)\b", t):
        return "remote"
    return None  # unknown: never claim on-site without evidence

def extract_experience(text: str):
    t = (text or "").lower()
    m = re.search(r"(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*(?:years|yrs|year)", t)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if 0 <= lo <= hi <= 40:
            return lo, hi
    m = re.search(r"(\d{1,2})\s*\+?\s*(?:years|yrs|year)", t)
    if m and int(m.group(1)) <= 40:
        return int(m.group(1)), None
    if re.search(r"\b(fresher|freshers|entry.level|graduate)\b", t):
        return 0, 1
    return None, None

def extract_skills(text: str) -> list:
    t = " " + (text or "").lower() + " "
    return [s for s in SKILL_VOCAB
            if re.search(r"(?<![a-z0-9])" + re.escape(s) + r"(?![a-z0-9])", t)]

def parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None

def is_safe_url(url: str) -> bool:
    """http(s) only, real hostname, no localhost / private-IP targets."""
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https") or not p.hostname or len(url) > 2000:
        return False
    host = p.hostname.lower()
    if host == "localhost" or host.endswith((".local", ".internal")):
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    except ValueError:
        pass
    return True

def validate(job: NormalizedJob) -> Optional[str]:
    """Return an error string if the job must be rejected, else None."""
    if not job.title or not job.company or not job.source_job_id:
        return "missing title/company/source_job_id"
    if not is_safe_url(job.url):
        return "unsafe or invalid url"
    if job.salary_min and job.salary_max and job.salary_min > job.salary_max:
        job.salary_min, job.salary_max = job.salary_max, job.salary_min
    return None