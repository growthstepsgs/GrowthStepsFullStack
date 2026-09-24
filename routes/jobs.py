import os
import hmac
import logging
from datetime import datetime, timezone
from functools import wraps
from flask import (Blueprint, render_template, request, jsonify, session,
                   redirect, url_for, flash, abort)

from jobs_engine.db import admin_db
from jobs_engine.matching import match_score
from jobs_engine.normalize import is_safe_url
from jobs_engine import aggregator
from jobs_engine.providers import get_providers

log = logging.getLogger("jobs.routes")
bp = Blueprint("jobs", __name__)


# ── helpers ────────────────────────────────────────────────────────────────
# NOTE: the env-based admin login stores session["user_id"] = None, so we treat
# "logged in" as "has a role", and only require a real user_id for save/apply.
def _logged_in():
    return bool(session.get("role"))

def _uid():
    return session.get("user_id")

def page_login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not _logged_in():
            session["next_url"] = request.full_path.rstrip("?")   # used by the auth.py patch
            flash("Please log in to search jobs.", "info")
            return redirect(url_for("auth.login"))
        return fn(*a, **kw)
    return wrapper

def api_login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not _logged_in():
            return jsonify(error="login_required"), 401
        if request.method != "GET" and request.headers.get("X-Requested-With") != "fetch":
            return jsonify(error="bad_request"), 400
        return fn(*a, **kw)
    return wrapper


# ── pages ──────────────────────────────────────────────────────────────────
@bp.route("/jobs")
@page_login_required
def jobs_page():
    sources = [{"name": p.name, "label": p.label} for p in get_providers()]
    return render_template("jobs/jobs.html", sources=sources)

@bp.route("/jobs/dashboard")
@page_login_required
def dashboard_page():
    return render_template("jobs/dashboard.html")


# ── search API ─────────────────────────────────────────────────────────────
def _int(name):
    v = request.args.get(name, "").strip()
    return int(v) if v.isdigit() else None

@bp.route("/api/jobs")
@api_login_required
def api_jobs():
    a = request.args
    modes = [m for m in a.getlist("mode") if m in ("remote", "hybrid", "onsite")] or None
    sources = [s for s in a.getlist("source") if s.isalnum()] or None
    sort = a.get("sort", "relevance")
    if sort not in ("relevance", "newest", "salary"):
        sort = "relevance"
    page = max(_int("page") or 1, 1)
    limit = 20

    try:
        res = admin_db().rpc("search_jobs", {
            "p_q": a.get("q", "")[:100] or None,
            "p_location": a.get("location", "")[:100] or None,
            "p_modes": modes, "p_exp": _int("exp"), "p_min_salary": _int("min_salary"),
            "p_days": _int("days"), "p_sources": sources, "p_sort": sort,
            "p_limit": limit, "p_offset": (page - 1) * limit,
        }).execute().data
    except Exception as exc:
        log.exception("search failed")
        return jsonify(error="search_failed"), 500
    items = res["items"]

    uid = _uid()
    if uid and items:
        db, ids = admin_db(), [j["id"] for j in items]
        try:
            saved = {r["job_id"] for r in db.table("saved_jobs").select("job_id").eq("user_id", uid).in_("job_id", ids).execute().data}
            applied = {r["job_id"] for r in db.table("applied_jobs").select("job_id").eq("user_id", uid).in_("job_id", ids).execute().data}
            prof = (db.table("profiles").select("skills,experience_years,preferred_location").eq("id", uid).limit(1).execute().data or [{}])[0]
        except Exception:
            saved, applied, prof = set(), set(), {}
        for j in items:
            j["saved"], j["applied"] = j["id"] in saved, j["id"] in applied
            j["match"] = match_score(prof, j)
    for j in items:
        j["description"] = (j.get("description") or "")[:300]
    return jsonify(total=res["total"], page=page, per_page=limit, items=items)


# ── original job redirect (also records "recently viewed") ─────────────────
@bp.route("/jobs/go/<job_id>/<posting_id>")
@page_login_required
def go_original(job_id, posting_id):
    rows = (admin_db().table("job_postings").select("url")
            .eq("id", posting_id).eq("job_id", job_id).limit(1).execute().data)
    if not rows or not is_safe_url(rows[0]["url"]):
        abort(404)   # URL comes from OUR database, never the query string -> no open redirect
    if _uid():
        try:
            admin_db().table("job_views").upsert({
                "user_id": _uid(), "job_id": job_id,
                "viewed_at": datetime.now(timezone.utc).isoformat()}).execute()
        except Exception:
            log.exception("could not record view")
    return redirect(rows[0]["url"], code=302)


# ── save / applied ─────────────────────────────────────────────────────────
def _toggle(table, job_id):
    db, uid = admin_db(), _uid()
    exists = db.table(table).select("job_id").eq("user_id", uid).eq("job_id", job_id).limit(1).execute().data
    if exists:
        db.table(table).delete().eq("user_id", uid).eq("job_id", job_id).execute()
        return False
    db.table(table).insert({"user_id": uid, "job_id": job_id}).execute()
    return True

def _no_profile():
    return jsonify(error="no_profile",
                   message="The built-in admin account has no student profile, so it can't save jobs."), 400

@bp.route("/api/jobs/<job_id>/save", methods=["POST"])
@api_login_required
def api_save(job_id):
    if not _uid():
        return _no_profile()
    return jsonify(saved=_toggle("saved_jobs", job_id))

@bp.route("/api/jobs/<job_id>/applied", methods=["POST"])
@api_login_required
def api_applied(job_id):
    if not _uid():
        return _no_profile()
    return jsonify(applied=_toggle("applied_jobs", job_id))


# ── dashboard data ─────────────────────────────────────────────────────────
@bp.route("/api/jobs/dashboard")
@api_login_required
def api_dashboard():
    if not _uid():
        return jsonify(saved=[], applied=[], recent=[])
    db, uid = admin_db(), _uid()
    cols = "jobs(id,title,company,location,work_mode,exp_min,exp_max,skills,posted_at,job_postings(id,source))"

    def grab(table, ts, n=50):
        rows = db.table(table).select(f"{ts},{cols}").eq("user_id", uid).order(ts, desc=True).limit(n).execute().data
        return [{**r["jobs"], "at": r[ts]} for r in rows if r.get("jobs")]

    return jsonify(saved=grab("saved_jobs", "created_at"),
                   applied=grab("applied_jobs", "applied_at"),
                   recent=grab("job_views", "viewed_at", 20))


# ── ingestion ──────────────────────────────────────────────────────────────
# ← changed: Tamil Nadu-focused queries mixed in, so the cron pulls local
# postings (Coimbatore/Chennai) instead of only pan-India results.
DEFAULT_QUERIES = ["python developer", "python developer coimbatore",
                   "web developer", "java developer chennai",
                   "data analyst", "machine learning",
                   "software engineer fresher", "react developer",
                   "devops engineer", "internship"]

def _run_ingestion():
    per_run = int(os.getenv("JOB_QUERIES_PER_RUN", "3"))   # set to 10 in Vercel env so one daily run covers all queries
    now = datetime.now(timezone.utc)
    start = (now.timetuple().tm_yday * per_run) % len(DEFAULT_QUERIES)
    qs = [DEFAULT_QUERIES[(start + i) % len(DEFAULT_QUERIES)] for i in range(per_run)]
    out = aggregator.run(qs, pages=1)
    aggregator.expire_stale()   # ← changed: 10 days (new aggregator default), was 30
    return out

@bp.route("/api/jobs/refresh")   # Vercel Cron sends: Authorization: Bearer <CRON_SECRET>
def cron_refresh():
    secret = os.getenv("CRON_SECRET", "")
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not secret or not hmac.compare_digest(supplied, secret):
        abort(401)
    return jsonify(_run_ingestion())

@bp.route("/admin/jobs/refresh", methods=["POST"])
@api_login_required
def admin_refresh():
    if session.get("role") != "admin":
        return jsonify(error="forbidden"), 403
    return jsonify(_run_ingestion())