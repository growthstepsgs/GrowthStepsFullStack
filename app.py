"""
GS-Growth Steps — Flask backend
────────────────────────────────
Static site converted to a Flask app with a simple auth layer backed
by Supabase (auth + `profiles` + `requests` + `gallery_photos` tables).

Schema recap (see growth_steps_schema.sql + requests_schema.sql +
gallery_schema.sql):
  profiles(id, full_name, role['admin'|'employee'|'student'], created_at)
  requests(id, employee_id, title, description, status, admin_note,
           created_at, updated_at)
  gallery_photos(id, image_url, storage_path, caption, uploaded_by,
                 created_at)

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
server-side reads/writes to `requests`, `profiles`, and `gallery_photos`
go through the service-role client (supabase_admin), with ownership
checks enforced in Python (e.g. .eq("employee_id", user_id)) rather
than relying on RLS at request time. The RLS policies in the *_schema.sql
files still protect the tables from anything hitting them directly
with the anon key.

IMPORTANT (Storage): gallery uploads go to a Supabase Storage bucket.
You must create a bucket named GALLERY_BUCKET (below) in the Supabase
dashboard (Storage -> New bucket) and mark it Public, or
get_public_url() will return URLs that 403 when loaded.

Run:
  pip install -r requirements.txt
  cp .env.example .env      # fill in your Supabase project URL + keys
  flask --app app run --debug
"""
#google signin implementation
import secrets
import hashlib
import base64
import urllib.parse

import httpx

#33333333333333333333333333333

from datetime import datetime, timezone
import os
import uuid
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash
)
from werkzeug.utils import secure_filename
from supabase import create_client, Client
from werkzeug.middleware.proxy_fix import ProxyFix

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

# Gallery / Storage config
GALLERY_BUCKET = "Gallery"  # must match the bucket name created in Supabase Storage (set Public)
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}


def _allowed_image(filename: str) -> bool:
    return (
        bool(filename)
        and "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS
    )


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
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
        "dashboard's employee list, and the requests/gallery features will be "
        "limited by RLS. Add the service_role key (Project Settings -> API -> "
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
    courses = []
    client = supabase_admin or supabase
    if client:
        try:
            res = (
                client.table("courses")
                .select("*")
                .eq("is_active", True)
                .order("created_at", desc=True)
                .execute()
            )
            courses = res.data or []
        except Exception as exc:
            print(f"courses fetch failed: {exc}")
    return render_template("available_courses.html", courses=courses)


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

        if role == "employee":
            return redirect(url_for("employee_dashboard"))
        elif role == "student":
            return redirect(url_for("student_dashboard"))
        return redirect(url_for("home"))

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
                # Save name/email for admin visibility; leave role as 'student' (trigger default)
                supabase_admin.table("profiles").update({
                    "full_name": full_name,
                    "email": email,
                }).eq("id", user.id).execute()
            except Exception:
                pass

        flash("Account created! Check your email to confirm, then log in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# ── GOOGLE OAUTH ───────────────────────────────────────────────────

def _generate_pkce():
    """Generate PKCE verifier + challenge for OAuth."""
    verifier = base64.urlsafe_b64encode(
        secrets.token_bytes(32)
    ).rstrip(b"=").decode("utf-8")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode("utf-8")
    return verifier, challenge


@app.route("/auth/google")
def auth_google():
    """Redirect user to Google's consent screen via Supabase."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        flash("Supabase isn't configured.", "error")
        return redirect(url_for("login"))

    verifier, challenge = _generate_pkce()
    session["oauth_verifier"] = verifier
    next_param = request.args.get("next", "")
    if next_param.startswith("/"):
        session["oauth_next"] = next_param
    else:
        session["oauth_next"] = url_for("employee_dashboard")

    callback_url = url_for("auth_callback", _external=True)

    params = {
        "provider": "google",
        "redirect_to": callback_url,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    qs = urllib.parse.urlencode(params)
    return redirect(f"{SUPABASE_URL}/auth/v1/authorize?{qs}")


@app.route("/auth/callback")
def auth_callback():
    """Supabase redirects back here after Google approval."""
    code = request.args.get("code")
    verifier = session.pop("oauth_verifier", None)

    if not code or not verifier:
        flash("Sign-in failed — session expired or denied.", "error")
        return redirect(url_for("login"))

    # Exchange the code for user info
    try:
        r = httpx.post(
            f"{SUPABASE_URL}/auth/v1/token?grant_type=pkce",
            headers={
                "apikey": SUPABASE_KEY,
                "Content-Type": "application/json",
            },
            json={"auth_code": code, "code_verifier": verifier},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        flash(f"Google sign-in failed: {exc}", "error")
        return redirect(url_for("login"))

    user = data.get("user")
    if not user:
        flash("Could not retrieve user info.", "error")
        return redirect(url_for("login"))

    user_id = user.get("id")
    email = user.get("email", "").lower()

    # Fetch role from profiles (new users keep the default 'student' from the trigger)
    role = "student"
    try:
        prof = (
            supabase.table("profiles")
            .select("role")
            .eq("id", user_id)
            .single()
            .execute()
        )
        if prof.data:
            role = prof.data.get("role", "student")
    except Exception:
        pass

    # Save email for admin visibility
    if supabase_admin:
        try:
            supabase_admin.table("profiles").update({
                "email": email,
            }).eq("id", user_id).execute()
        except Exception:
            pass

    session["user_email"] = email
    session["user_id"] = user_id
    session["role"] = role

    flash("Signed in with Google.", "success")

    if role == "employee":
        return redirect(url_for("employee_dashboard"))
    elif role == "student":
        return redirect(url_for("student_dashboard"))
    return redirect(url_for("home"))

# ── DASHBOARDS ──────────────────────────────────────────────────────

@app.route("/dashboard/employee")
@login_required
def employee_dashboard():
    role = session.get("role")
    if role == "admin":
        return redirect(url_for("admin_dashboard"))
    if role == "student":
        return redirect(url_for("student_dashboard"))
    return render_template(
        "employee_dashboard.html",
        email=session.get("user_email"),
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


# ── PUBLIC GALLERY ───────────────────────────────────────────────────
@app.route("/gallery")
def gallery():
    photos = []
    client = supabase_admin or supabase
    if client:
        try:
            res = (
                client.table("gallery_photos")
                .select("*")
                .order("created_at", desc=True)
                .execute()
            )
            photos = res.data or []
        except Exception as exc:
            print(f"gallery fetch failed: {exc}")
            photos = []
    return render_template("gallery.html", photos=photos)

@app.route("/dashboard/student")
@login_required
def student_dashboard():
    role = session.get("role")
    if role == "admin":
        return redirect(url_for("admin_dashboard"))
    if role == "employee":
        return redirect(url_for("employee_dashboard"))
    return render_template("student_dashboard.html", email=session.get("user_email"))


@app.route("/dashboard/admin")
@admin_required
def admin_dashboard():
    users = []
    client = supabase_admin or supabase
    if client:
        try:
            res = client.table("profiles").select("*").order("created_at", desc=True).execute()
            users = res.data or []
        except Exception:
            users = []

    course_count = 0
    if client:
        try:
            res = client.table("courses").select("*").execute()
            course_count = len(res.data or [])
        except Exception:
            pass

    student_count = sum(1 for u in users if u.get("role") == "student")
    employee_count = sum(1 for u in users if u.get("role") == "employee")

    return render_template(
        "admin_dashboard.html",
        email=session.get("user_email"),
        users=users,
        course_count=course_count,
        student_count=student_count,
        employee_count=employee_count,
    )


@app.route("/dashboard/admin/users/<user_id>/role", methods=["POST"])
@admin_required
def admin_update_role(user_id):
    new_role = request.form.get("role", "").strip()
    if new_role not in ("student", "employee"):
        flash("Invalid role.", "error")
        return redirect(url_for("admin_dashboard"))

    client = supabase_admin or supabase
    if not client:
        flash("Supabase isn't configured.", "error")
        return redirect(url_for("admin_dashboard"))

    try:
        client.table("profiles").update({"role": new_role}).eq("id", user_id).execute()
        flash(f"Role updated to {new_role}.", "success")
    except Exception as exc:
        flash(f"Could not update role: {exc}", "error")

    return redirect(url_for("admin_dashboard"))
# ── SEO: SITEMAP & ROBOTS.TXT ───────────────────────────────────────
@app.route("/sitemap.xml")
def sitemap():
    """Dynamic XML sitemap of all public, indexable pages."""
    pages = [
        {"loc": url_for("home", _external=True),              "priority": "1.0",  "changefreq": "weekly"},
        {"loc": url_for("courses", _external=True),           "priority": "0.8",  "changefreq": "weekly"},
        {"loc": url_for("available_courses", _external=True), "priority": "0.8",  "changefreq": "weekly"},
        {"loc": url_for("services", _external=True),          "priority": "0.8",  "changefreq": "monthly"},
        {"loc": url_for("workshop", _external=True),          "priority": "0.7",  "changefreq": "monthly"},
        {"loc": url_for("gallery", _external=True),           "priority": "0.7",  "changefreq": "weekly"},
        {"loc": url_for("login", _external=True),             "priority": "0.5",  "changefreq": "yearly"},
        {"loc": url_for("signup", _external=True),            "priority": "0.5",  "changefreq": "yearly"},
    ]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml_lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for p in pages:
        xml_lines.append("  <url>")
        xml_lines.append(f"    <loc>{p['loc']}</loc>")
        xml_lines.append(f"    <lastmod>{now}</lastmod>")
        xml_lines.append(f"    <changefreq>{p['changefreq']}</changefreq>")
        xml_lines.append(f"    <priority>{p['priority']}</priority>")
        xml_lines.append("  </url>")
    xml_lines.append("</urlset>")

    return "\n".join(xml_lines), 200, {"Content-Type": "application/xml"}


@app.route("/robots.txt")
def robots():
    """Tell crawlers what they may index and where the sitemap lives."""
    base = request.url_root.rstrip("/")
    lines = [
        "User-agent: *",
        "Disallow: /dashboard/",
        "Disallow: /admin/",
        "Disallow: /login",
        "Disallow: /signup",
        "",
        f"Sitemap: {base}/sitemap.xml",
        "",
    ]
    return "\n".join(lines), 200, {"Content-Type": "text/plain"}

@app.route("/admin/cleanup-orphaned-photos")
@admin_required
def cleanup_orphaned_photos():
    client = supabase_admin or supabase
    if not client:
        flash("Supabase isn't configured.", "error")
        return redirect(url_for("admin_gallery"))

    deleted = 0
    try:
        res = client.table("gallery_photos").select("*").execute()
        for p in (res.data or []):
            try:
                # HEAD-check the storage object; if missing, delete the row
                client.storage.from_(GALLERY_BUCKET).download(p["storage_path"])
            except Exception:
                client.table("gallery_photos").delete().eq("id", p["id"]).execute()
                deleted += 1
    except Exception as exc:
        flash(f"Cleanup failed: {exc}", "error")
        return redirect(url_for("admin_gallery"))

    flash(f"Cleanup done — removed {deleted} orphaned row(s).", "success")
    return redirect(url_for("admin_gallery"))

# ── ADMIN GALLERY MANAGEMENT ─────────────────────────────────────────
@app.route("/admin/admin_gallery", methods=["GET", "POST"])
@admin_required
def admin_gallery():
    client = supabase_admin or supabase

    if request.method == "POST":
        caption = request.form.get("caption", "").strip()
        file = request.files.get("image")

        if not file or file.filename == "":
            flash("Please choose an image to upload.", "error")
            return redirect(url_for("admin_gallery"))

        if not _allowed_image(file.filename):
            flash("Unsupported file type — use jpg, png, webp, or gif.", "error")
            return redirect(url_for("admin_gallery"))

        if not client:
            flash("Supabase isn't configured on the server.", "error")
            return redirect(url_for("admin_gallery"))

        ext = secure_filename(file.filename).rsplit(".", 1)[1].lower()
        storage_path = f"{uuid.uuid4().hex}.{ext}"

        try:
            file_bytes = file.read()
            client.storage.from_(GALLERY_BUCKET).upload(
                storage_path,
                file_bytes,
                {"content-type": file.mimetype},
            )
            public_url = client.storage.from_(GALLERY_BUCKET).get_public_url(storage_path)

            client.table("gallery_photos").insert({
                "image_url": public_url,
                "storage_path": storage_path,
                "caption": caption,
            }).execute()

            flash("Photo uploaded.", "success")
        except Exception as exc:
            flash(f"Upload failed: {exc}", "error")

        return redirect(url_for("admin_gallery"))

    photos = []
    if client:
        try:
            res = (
                client.table("gallery_photos")
                .select("*")
                .order("created_at", desc=True)
                .execute()
            )
            photos = res.data or []
        except Exception:
            photos = []

    return render_template("admin_gallery.html", photos=photos)

@app.route("/admin/courses", methods=["GET", "POST"])
@admin_required
def admin_courses():
    client = supabase_admin or supabase

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        price = request.form.get("price", "0").strip()
        original_price = request.form.get("original_price", "").strip()
        duration = request.form.get("duration", "").strip()
        schedule = request.form.get("schedule", "").strip()
        mode = request.form.get("mode", "").strip()
        status = request.form.get("status", "coming_soon")
        tags_raw = request.form.get("tags", "").strip()
        cta_link = request.form.get("cta_link", "").strip()
        cta_label = request.form.get("cta_label", "View Course Details").strip()

        if not title:
            flash("Course title is required.", "error")
            return redirect(url_for("admin_courses"))

        try:
            payload = {
                "title": title,
                "description": description,
                "price": int(price) if price else 0,
                "duration": duration,
                "schedule": schedule,
                "mode": mode,
                "status": status,
                "tags": [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else [],
                "cta_link": cta_link,
                "cta_label": cta_label,
            }
            if original_price:
                payload["original_price"] = int(original_price)

            client.table("courses").insert(payload).execute()
            flash("Course published successfully.", "success")
        except Exception as exc:
            flash(f"Failed to publish course: {exc}", "error")
        return redirect(url_for("admin_courses"))

    courses = []
    if client:
        try:
            res = client.table("courses").select("*").order("created_at", desc=True).execute()
            courses = res.data or []
        except Exception:
            courses = []
    return render_template("admin_courses.html", courses=courses)


@app.route("/admin/courses/<course_id>/delete", methods=["POST"])
@admin_required
def admin_delete_course(course_id):
    client = supabase_admin or supabase
    if not client:
        flash("Supabase isn't configured.", "error")
        return redirect(url_for("admin_courses"))
    try:
        client.table("courses").delete().eq("id", course_id).execute()
        flash("Course deleted.", "success")
    except Exception as exc:
        flash(f"Could not delete course: {exc}", "error")
    return redirect(url_for("admin_courses"))

@app.route("/dashboard/admin/gallery/<photo_id>/delete", methods=["POST"])
@admin_required
def admin_delete_gallery_photo(photo_id):
    client = supabase_admin or supabase
    if not client:
        flash("Supabase isn't configured on the server.", "error")
        return redirect(url_for("admin_gallery"))

    try:
        row = (
            client.table("gallery_photos")
            .select("storage_path")
            .eq("id", photo_id)
            .single()
            .execute()
        )
        if row.data:
            client.storage.from_(GALLERY_BUCKET).remove([row.data["storage_path"]])
        client.table("gallery_photos").delete().eq("id", photo_id).execute()
        flash("Photo deleted.", "success")
    except Exception as exc:
        flash(f"Could not delete photo: {exc}", "error")

    return redirect(url_for("admin_gallery"))


# ── ADMIN REQUESTS MANAGEMENT ────────────────────────────────────────
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
