"""Fetch -> normalize -> validate -> dedupe -> store (batched) -> log.
Batched so one query costs ~6 DB calls, which fits inside a Vercel function time limit."""
import logging
from datetime import datetime, timedelta, timezone
from .db import admin_db
from .providers import get_providers
from .normalize import validate

log = logging.getLogger("jobs.aggregator")


def store(jobs):
    """jobs: list[NormalizedJob] from ONE source. Returns {inserted, updated, duplicates}."""
    stats = {"inserted": 0, "updated": 0, "duplicates": 0}
    if not jobs:
        return stats
    db, now = admin_db(), datetime.now(timezone.utc).isoformat()
    source = jobs[0].source

    uniq = {}
    for j in jobs:
        uniq.setdefault(j.source_job_id, j)
    jobs = list(uniq.values())

    # 1) listings we already have from this source -> just refresh last_seen
    rows = (db.table("job_postings").select("source_job_id,job_id").eq("source", source)
            .in_("source_job_id", [j.source_job_id for j in jobs]).execute().data or [])
    known = {r["source_job_id"]: r["job_id"] for r in rows}
    if known:
        db.table("jobs").update({"last_seen_at": now, "is_active": True}).in_("id", list(set(known.values()))).execute()
    stats["updated"] = len(known)

    fresh = [j for j in jobs if j.source_job_id not in known]
    if not fresh:
        return stats

    # 2) same job (title+company+city) already stored, maybe from another platform -> reuse it
    keys = list({j.dedupe_key for j in fresh})
    ex = db.table("jobs").select("id,dedupe_key").in_("dedupe_key", keys).execute().data or []
    key_to_id = {r["dedupe_key"]: r["id"] for r in ex}
    if key_to_id:
        db.table("jobs").update({"last_seen_at": now, "is_active": True}).in_("id", list(key_to_id.values())).execute()

    # 3) insert genuinely new jobs in one call
    new_rows, seen = [], set()
    for j in fresh:
        k = j.dedupe_key
        if k in key_to_id or k in seen:
            continue
        seen.add(k)
        new_rows.append({
            "dedupe_key": k, "title": j.title, "company": j.company, "location": j.location,
            "work_mode": j.work_mode, "exp_min": j.exp_min, "exp_max": j.exp_max,
            "salary_min": j.salary_min, "salary_max": j.salary_max,
            "salary_currency": j.salary_currency, "skills": j.skills, "description": j.description,
            "posted_at": j.posted_at.isoformat() if j.posted_at else None,
        })
    if new_rows:
        for r in db.table("jobs").insert(new_rows).execute().data:
            key_to_id[r["dedupe_key"]] = r["id"]
    stats["inserted"] = len(new_rows)
    stats["duplicates"] = len(fresh) - len(new_rows)

    # 4) one posting row per source listing, each keeping its own original URL
    #    (guarded: only jobs that actually resolved to a jobs.id — defensive)
    posting_rows = [
        {"job_id": key_to_id[j.dedupe_key], "source": j.source,
         "source_job_id": j.source_job_id, "url": j.url}
        for j in fresh if j.dedupe_key in key_to_id
    ]
    if posting_rows:
        db.table("job_postings").insert(posting_rows).execute()
    return stats


def run(queries, location="", pages=1):
    db, summary = admin_db(), []
    for provider in get_providers():
        for q in queries:
            stats = {"fetched": 0, "inserted": 0, "updated": 0, "duplicates": 0, "rejected": 0}
            status, err, valid = "ok", None, []
            try:
                for page in range(1, pages + 1):
                    raws = provider.fetch(q, location, page)
                    stats["fetched"] += len(raws)
                    for raw in raws:
                        try:
                            job = provider.normalize(raw)
                            if not job or validate(job):
                                stats["rejected"] += 1
                            else:
                                valid.append(job)
                        except Exception:
                            log.exception("bad record from %s", provider.name)
                            stats["rejected"] += 1
                    if not raws:
                        break
                stats.update(store(valid))
            except Exception as e:  # one failing provider/query must not break the rest
                status, err = "error", str(e)[:500]
                log.exception("provider %s failed for %r", provider.name, q)
            try:
                db.table("ingestion_logs").insert(
                    {"source": provider.name, "query": q, "status": status, "error": err, **stats}).execute()
            except Exception:
                log.exception("could not write ingestion log")
            summary.append({"source": provider.name, "query": q, "status": status, **stats})
    return summary


def expire_stale(days=10):   # was 30 — a job unseen for 10 days is almost certainly delisted
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    admin_db().table("jobs").update({"is_active": False}).lt("last_seen_at", cutoff).execute()