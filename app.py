"""
GS-Growth Steps — Flask backend
────────────────────────────────
Static site converted to a Flask app with a simple auth layer backed
by Supabase (auth + `profiles` + `requests` tables).

Schema recap (see growth_steps_schema.sql + requests_schema.sql):
  profiles(id, full_name, role['admin'|'employee'|'student'], created_at)
  requests(id, employee_id, title, description, status, admin_note,
           created_at, updated_at)

  A trigger auto-inserts a `profiles` row (role='student') whenever a
  new auth.users row is created — the app does NOT insert into
  `profiles` itself, it only promotes the role after signup.

Roles:
  - Admin    -> hardcoded to rsvijaysarathi123@gmail.com (single owner account,
                also set as role='admin' directly in SQL). Not a Supabase-auth login.
  - Employee -> anyone who signs up via /signup. Trigger creates them as
                'student' by default; the app immediately promotes them
                to 'employee' using the service-role client.

IMPORTANT: Flask's session and Supabase Auth's session are separate.
This app never forwards the logged-in user's JWT to PostgREST, so all
server-side reads/writes to `requests` and `profiles` go through the
service-role client (supabase_admin), with ownership checks enforced
in Python (e.g. .eq("employee_id", user_id)) rather than relying on
RLS at request time. The RLS policies in requests_schema.sql still
protect the table from anything hitting it directly with the anon key.

Run:
  pip install -r requirements.txt
  cp .env.example .env      # fill in your Supabase project URL + keys
  flask --app app run --debug
"""

import os
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash
)
from supabase import create_client, Client

# Load .env from the SAME folder as this file, regardless of the
# directory you launch `flask run` / `python app.py` from.
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

# ── CONFIG ──────────────────────────────────────────────────────────
SUPABASE_URL         = os.environ.get("SUPABASE_URL")
SUPABASE_KEY         = os.environ.get("SUPABASE_KEY")          # anon/public key -> sign in/up
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")  # service_role key -> admin reads/writes, bypasses RLS

ADMIN_EMAIL    = "rsvijaysarathi123@gmail.com"
ADMIN_PASSWORD = "v2v24123@v2v24123"

VALID_STATUSES = {"pending", "in_review", "approved", "rejected"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

if not SUPABASE_URL or not SUPABASE_KEY:
    print(
        "\n⚠️  SUPABASE NOT CONFIGURED\n"
        f"   Expected a .env file at: {BASE_DIR / '.env'}\n"
        f"   SUPABASE_URL set? {'yes' if SUPABASE_URL else 'NO'}\n"
        f"   SUPABASE_KEY set? {'yes' if SUPABASE_KEY else 'NO'}\n"
        "   Fix:\n"
        "     1) cp .env.example .env   (in this exact folder, next to app.py)\n"
        "     2) Fill in SUPABASE_URL and SUPABASE_KEY from\n"
        "        Supabase -> Project Settings -> API -> Project URL / anon public key\n"
        "     3) Fully stop and restart flask -- env vars are only read at startup,\n"
        "        editing .env while the server is running has no effect.\n"
    )
if SUPABASE_URL and SUPABASE_KEY and not SUPABASE_SERVICE_KEY:
    print(
        "i  No SUPABASE_SERVICE_KEY set -- signup role-promotion, the admin "
        "dashboard's employee list, and the requests feature will be limited "
        "by RLS. Add the service_role key (Project Settings -> API -> "
        "service_role) to .env to enable them fully."
    )

supabase: Client | None = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

supabase_admin: Client | None = None
if SUPABASE_URL and SUPABASE_SERVICE_KEY:
    supabase_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
elif supabase:
    supabase_admin = supabase


# ── HELPERS ─────────────────────────────────────────────────────────
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_email"):
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admins only.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


# ── PUBLIC STATIC-STYLE PAGES (unchanged UI) ───────────────────────
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/courses")
def courses():
    return render_template("courses.html")


@app.route("/available-courses")
def available_courses():
    return render_template("available_courses.html")


@app.route("/services")
def services():
    return render_template("services.html")


@app.route("/workshop")
def workshop():
    return render_template("umm.html")


@app.route("/google1371138ddddc045a.html")
def google_verify():
    return app.send_static_file("google1371138ddddc045a.html")


# ── AUTH ────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        # 1) Admin login (hardcoded, single owner account — not a Supabase auth user)
        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
            session["user_email"] = email
            session["user_id"] = None
            session["role"] = "admin"
            return redirect(url_for("admin_dashboard"))

        # 2) Everyone else logs in through Supabase Auth
        if not supabase:
            flash(
                "Supabase isn't configured on the server yet — see the "
                "terminal log for what's missing.",
                "error",
            )
            return redirect(url_for("login"))

        try:
            result = supabase.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        except Exception as exc:
            flash(f"Invalid credentials: {exc}", "error")
            return redirect(url_for("login"))

        if not result.user:
            flash("Invalid email or password.", "error")
            return redirect(url_for("login"))

        role = "student"
        try:
            prof = (
                supabase.table("profiles")
                .select("role")
                .eq("id", result.user.id)
                .single()
                .execute()
            )
            if prof.data:
                role = prof.data.get("role", "student")
        except Exception:
            pass

        session["user_email"] = email
        session["user_id"] = result.user.id
        session["role"] = role
        return redirect(url_for("employee_dashboard"))

    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        full_name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if email == ADMIN_EMAIL:
            flash("This email is reserved.", "error")
            return redirect(url_for("signup"))

        if not supabase:
            flash(
                "Supabase isn't configured on the server yet — see the "
                "terminal log for what's missing.",
                "error",
            )
            return redirect(url_for("signup"))

        try:
            result = supabase.auth.sign_up({
                "email": email,
                "password": password,
                "options": {"data": {"full_name": full_name}},
            })
        except Exception as exc:
            flash(f"Could not sign up: {exc}", "error")
            return redirect(url_for("signup"))

        user = result.user
        if user and supabase_admin:
            try:
                supabase_admin.table("profiles").update(
                    {"role": "employee"}
                ).eq("id", user.id).execute()
            except Exception as exc:
                flash(
                    f"Account created, but role promotion failed ({exc}). "
                    "Ask an admin to set your role to 'employee' manually.",
                    "error",
                )
                return redirect(url_for("login"))
        elif user and not supabase_admin:
            flash(
                "Account created as a default 'student' — add "
                "SUPABASE_SERVICE_KEY to .env so new signups are "
                "automatically promoted to 'employee'.",
                "error",
            )
            return redirect(url_for("login"))

        flash("Account created! Check your email to confirm, then log in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# ── DASHBOARDS ──────────────────────────────────────────────────────
@app.route("/dashboard/employee")
@login_required
def employee_dashboard():
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))
    return render_template(
        "employee_dashboard.html",
        email=session.get("user_email"),
    )


@app.route("/dashboard/admin")
@admin_required
def admin_dashboard():
    employees = []
    client = supabase_admin or supabase
    if client:
        try:
            res = (
                client.table("profiles")
                .select("*")
                .eq("role", "employee")
                .execute()
            )
            employees = res.data or []
        except Exception:
            employees = []
    return render_template(
        "admin_dashboard.html",
        email=session.get("user_email"),
        employees=employees,
    )


# ── EMPLOYEE REQUESTS / PROPOSALS ───────────────────────────────────
@app.route("/dashboard/employee/requests", methods=["GET", "POST"])
@login_required
def employee_requests():
    if session.get("role") == "admin":
        return redirect(url_for("admin_requests"))

    user_id = session.get("user_id")
    client = supabase_admin or supabase

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()

        if not title or not description:
            flash("Please fill in both a title and a description.", "error")
            return redirect(url_for("employee_requests"))

        if not client or not user_id:
            flash("Could not submit request — please log in again.", "error")
            return redirect(url_for("employee_requests"))

        try:
            client.table("requests").insert({
                "employee_id": user_id,
                "title": title,
                "description": description,
            }).execute()
            flash("Your request has been submitted.", "success")
        except Exception as exc:
            flash(f"Could not submit request: {exc}", "error")

        return redirect(url_for("employee_requests"))

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
        "employee_requests.html",
        email=session.get("user_email"),
        my_requests=my_requests,
    )

@app.route("/dashboard/employee/sheets")
@login_required
def employee_sheets():
    return render_template(
        "employee_sheets.html",
        email=session.get("user_email")
    )

@app.route("/dashboard/admin/requests")
@admin_required
def admin_requests():
    client = supabase_admin or supabase
    all_requests = []
    if client:
        try:
            # NOTE: requests.employee_id references auth.users(id), not
            # profiles.id directly, so PostgREST can't auto-infer a
            # requests -> profiles embed (select("*, profiles(...)")
            # silently fails). Fetch both tables separately and merge
            # in Python instead.
            req_res = (
                client.table("requests")
                .select("*")
                .order("created_at", desc=True)
                .execute()
            )
            all_requests = req_res.data or []

            employee_ids = list({r["employee_id"] for r in all_requests if r.get("employee_id")})
            names_by_id = {}
            if employee_ids:
                prof_res = (
                    client.table("profiles")
                    .select("id, full_name")
                    .in_("id", employee_ids)
                    .execute()
                )
                names_by_id = {
                    p["id"]: p.get("full_name") for p in (prof_res.data or [])
                }

            for r in all_requests:
                r["employee_name"] = names_by_id.get(r.get("employee_id")) or "Unknown"
        except Exception as exc:
            print(f"admin_requests fetch failed: {exc}")
            all_requests = []

    return render_template(
        "admin_requests.html",
        email=session.get("user_email"),
        all_requests=all_requests,
    )


@app.route("/dashboard/admin/requests/<request_id>/update", methods=["POST"])
@admin_required
def admin_update_request(request_id):
    status = request.form.get("status", "").strip()
    admin_note = request.form.get("admin_note", "").strip()

    if status not in VALID_STATUSES:
        flash("Invalid status.", "error")
        return redirect(url_for("admin_requests"))

    client = supabase_admin or supabase
    if not client:
        flash("Supabase isn't configured on the server.", "error")
        return redirect(url_for("admin_requests"))

    try:
        client.table("requests").update({
            "status": status,
            "admin_note": admin_note,
        }).eq("id", request_id).execute()
        flash("Request updated.", "success")
    except Exception as exc:
        flash(f"Could not update request: {exc}", "error")

    return redirect(url_for("admin_requests"))


# ── CONTACT FORM (optional server-side handling; front-end already
#    uses EmailJS directly, this endpoint is available if you want to
#    move that logic server-side later) ─────────────────────────────
@app.route("/contact", methods=["POST"])
def contact():
    return redirect(request.referrer or url_for("home"))


if __name__ == "__main__":
    app.run(debug=True)