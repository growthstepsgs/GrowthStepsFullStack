from datetime import datetime, timezone
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash
)
from extensions import supabase, supabase_admin
from utils import login_required, _get_current_role

bp = Blueprint("employee", __name__)


@bp.route("/dashboard/employee")
@login_required
def employee_dashboard():
    user_id = session.get("user_id")
    role = _get_current_role(user_id)
    session["role"] = role

    if role == "admin":
        return redirect(url_for("admin.admin_dashboard"))
    if role == "student":
        return redirect(url_for("student.student_dashboard"))
    return render_template(
        "employee/employee_dashboard.html",
        email=session.get("user_email"),
    )


@bp.route("/dashboard/employee/requests", methods=["GET", "POST"])
@login_required
def employee_requests():
    if session.get("role") == "admin":
        return redirect(url_for("admin.admin_requests"))

    user_id = session.get("user_id")
    client = supabase_admin or supabase

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()

        if not title or not description:
            flash("Please fill in both a title and a description.", "error")
            return redirect(url_for("employee.employee_requests"))

        if not client or not user_id:
            flash("Could not submit request — please log in again.", "error")
            return redirect(url_for("employee.employee_requests"))

        try:
            client.table("requests").insert({
                "employee_id": user_id,
                "title": title,
                "description": description,
            }).execute()
            flash("Your request has been submitted.", "success")
        except Exception as exc:
            flash(f"Could not submit request: {exc}", "error")

        return redirect(url_for("employee.employee_requests"))

    my_requests = []
    if client and user_id:
        try:
            res = (
                client.table("requests")
                .select("*")
                .eq("employee_id", user_id)
                .order("created_at", desc=True)
                .execute()
            )
            my_requests = res.data or []
        except Exception:
            my_requests = []

    return render_template(
        "employee/employee_requests.html",
        email=session.get("user_email"),
        my_requests=my_requests,
    )


@bp.route("/dashboard/employee/sheets")
@login_required
def employee_sheets():
    return render_template(
        "employee/employee_sheets.html",
        email=session.get("user_email")
    )


@bp.route("/dashboard/employee/progress", methods=["GET", "POST"])
@login_required
def employee_progress():
    user_id = session.get("user_id")
    role = _get_current_role(user_id)
    session["role"] = role

    if role == "admin":
        return redirect(url_for("admin.admin_dashboard"))
    if role == "student":
        return redirect(url_for("student.student_dashboard"))

    client = supabase_admin or supabase
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if request.method == "POST":
        if not client or not user_id:
            flash("Could not save progress — please log in again.", "error")
            return redirect(url_for("employee.employee_progress"))

        tasks = request.form.get("tasks_completed", "").strip()
        hours = request.form.get("hours_worked", "0").strip()
        blockers = request.form.get("blockers", "").strip()
        plans = request.form.get("plans_tomorrow", "").strip()
        work_date = request.form.get("work_date", "").strip()
        if not work_date:
            work_date = today_str

        if not tasks:
            flash("Please describe what you worked on today.", "error")
            return redirect(url_for("employee.employee_progress"))

        try:
            hours_val = float(hours)
            if not (0.1 <= hours_val <= 24):
                raise ValueError
        except ValueError:
            flash("Hours worked must be between 0.1 and 24.", "error")
            return redirect(url_for("employee.employee_progress"))

        try:
            existing = (
                client.table("daily_progress")
                .select("id")
                .eq("employee_id", user_id)
                .eq("work_date", work_date)
                .execute()
            )
            payload = {
                "employee_id": user_id,
                "work_date": work_date,
                "tasks_completed": tasks,
                "hours_worked": hours_val,
                "blockers": blockers,
                "plans_tomorrow": plans,
            }
            if existing.data:
                client.table("daily_progress").update(payload).eq("id", existing.data[0]["id"]).execute()
                flash("Progress updated for " + work_date + ".", "success")
            else:
                client.table("daily_progress").insert(payload).execute()
                flash("Progress submitted for " + work_date + ".", "success")
        except Exception as exc:
            flash(f"Could not save progress: {exc}", "error")

        return redirect(url_for("employee.employee_progress"))

    my_progress = []
    today_entry = None
    if client and user_id:
        try:
            res = (
                client.table("daily_progress")
                .select("*")
                .eq("employee_id", user_id)
                .order("work_date", desc=True)
                .limit(30)
                .execute()
            )
            my_progress = res.data or []
            for p in my_progress:
                if p.get("work_date") == today_str:
                    today_entry = p
                    break
        except Exception as exc:
            print(f"progress fetch failed: {exc}")

    return render_template(
        "employee/employee_progress.html",
        email=session.get("user_email"),
        my_progress=my_progress,
        today_entry=today_entry,
        today=today_str,
    )