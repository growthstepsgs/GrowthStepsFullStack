from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash, abort
)
from extensions import supabase, supabase_admin
from utils import login_required, _get_current_role

bp = Blueprint("student", __name__)


@bp.route("/dashboard/student")
@login_required
def student_dashboard():
    user_id = session.get("user_id")
    role = _get_current_role(user_id)
    session["role"] = role

    if role == "admin":
        return redirect(url_for("admin.admin_dashboard"))
    if role == "employee":
        return redirect(url_for("employee.employee_dashboard"))

    user_id = session.get("user_id")
    client = supabase_admin or supabase

    all_courses = []
    enrollments = []
    course_contents = {}

    if client:
        try:
            res = client.table("courses").select("*").eq("is_active", True).order("created_at", desc=True).execute()
            all_courses = res.data or []
        except Exception:
            pass

        try:
            res = client.table("enrollments").select("*").eq("student_id", user_id).execute()
            enrollments = res.data or []
        except Exception:
            pass

        approved_ids = [e["course_id"] for e in enrollments if e.get("status") == "approved"]
        if approved_ids:
            try:
                res = client.table("course_contents").select("*").in_("course_id", approved_ids).order("sort_order").execute()
                for item in (res.data or []):
                    cid = item["course_id"]
                    if cid not in course_contents:
                        course_contents[cid] = []
                    course_contents[cid].append(item)
            except Exception:
                pass

    enrolled_ids = {e["course_id"] for e in enrollments}
    available_courses = [c for c in all_courses if c["id"] not in enrolled_ids]
    approved_enrollments = [e for e in enrollments if e.get("status") == "approved"]
    pending_enrollments = [e for e in enrollments if e.get("status") == "pending"]

    course_by_id = {c["id"]: c for c in all_courses}
    for e in approved_enrollments:
        e["course"] = course_by_id.get(e["course_id"])
    for e in pending_enrollments:
        e["course"] = course_by_id.get(e["course_id"])

    return render_template(
        "student/student_dashboard.html",
        email=session.get("user_email"),
        approved_enrollments=approved_enrollments,
        pending_enrollments=pending_enrollments,
        available_courses=available_courses,
        course_contents=course_contents,
    )


@bp.route("/enroll/<course_id>", methods=["POST"])
@login_required
def enroll_course(course_id):
    user_id = session.get("user_id")
    role = session.get("role")

    if role != "student":
        flash("Only students can enroll in courses.", "error")
        return redirect(url_for("public.available_courses"))

    client = supabase_admin or supabase
    if not client or not user_id:
        flash("Could not process enrollment.", "error")
        return redirect(url_for("public.available_courses"))

    try:
        existing = client.table("enrollments").select("*").eq("student_id", user_id).eq("course_id", course_id).execute()
        if existing.data:
            flash("You are already enrolled in this course.", "info")
            return redirect(url_for("student.student_dashboard"))

        client.table("enrollments").insert({
            "student_id": user_id,
            "course_id": course_id,
            "status": "pending",
        }).execute()
        flash("Enrollment request submitted! Waiting for admin approval.", "success")
    except Exception as exc:
        flash(f"Enrollment failed: {exc}", "error")

    return redirect(url_for("student.student_dashboard"))


@bp.route("/course/<course_id>/content/<content_id>")
@login_required
def course_content(course_id, content_id):
    user_id = session.get("user_id")
    role = session.get("role")

    if role != "admin":
        client = supabase_admin or supabase
        if client:
            try:
                res = client.table("enrollments").select("*") \
                    .eq("student_id", user_id) \
                    .eq("course_id", course_id) \
                    .eq("status", "approved") \
                    .execute()
                if not res.data:
                    flash("You are not enrolled in this course.", "error")
                    return redirect(url_for("student.student_dashboard"))
            except Exception:
                flash("Could not verify enrollment.", "error")
                return redirect(url_for("student.student_dashboard"))

    client = supabase_admin or supabase
    content = None
    if client:
        try:
            res = client.table("course_contents").select("*") \
                .eq("id", content_id) \
                .eq("course_id", course_id) \
                .single().execute()
            content = res.data
        except Exception:
            pass

    if not content:
        abort(404)

    if content.get("url"):
        return redirect(content["url"])

    return render_template("course_content.html", content=content)