"""Transparent match score. Every point comes from data on the job; nothing is invented."""

def match_score(profile: dict, job: dict):
    user_skills = {s.lower() for s in (profile.get("skills") or [])}
    job_skills = [s.lower() for s in (job.get("skills") or [])]
    if not user_skills or not job_skills:
        return None  # not enough data to score honestly

    matched = [s for s in job_skills if s in user_skills]
    missing = [s for s in job_skills if s not in user_skills]
    score = 70 * len(matched) / len(job_skills)
    reasons = [f"Matches {len(matched)} of {len(job_skills)} skills listed in the job"]

    yrs, lo, hi = profile.get("experience_years"), job.get("exp_min"), job.get("exp_max")
    if yrs is not None and lo is not None:
        band = f"{lo}-{hi}" if hi else f"{lo}+"
        if yrs >= lo and (hi is None or yrs <= hi + 1):
            score += 20
            reasons.append(f"Your {yrs} yr experience fits the {band} yr requirement")
        else:
            reasons.append(f"Job asks for {band} yrs; you have {yrs}")
    pref, loc = (profile.get("preferred_location") or "").lower(), (job.get("location") or "").lower()
    if job.get("work_mode") == "remote" or (pref and pref in loc):
        score += 10
        reasons.append("Location / work mode fits your preference")

    return {"score": round(score), "matched": matched, "missing": missing, "reasons": reasons}