import secrets
import hashlib
import base64
import urllib.parse
import httpx
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash
)
from extensions import supabase, supabase_admin
from config import SUPABASE_URL, SUPABASE_KEY, ADMIN_EMAIL, ADMIN_PASSWORD
from utils import login_required

bp = Blueprint("auth", __name__)


def _generate_pkce():
    verifier = base64.urlsafe_b64encode(
        secrets.token_bytes(32)
    ).rstrip(b"=").decode("utf-8")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode("utf-8")
    return verifier, challenge


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
            session["user_email"] = email
            session["user_id"] = None
            session["role"] = "admin"
            return redirect(url_for("admin.admin_dashboard"))

        if not supabase:
            flash("Supabase isn't configured.", "error")
            return redirect(url_for("auth.login"))

        try:
            result = supabase.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        except Exception as exc:
            flash(f"Invalid credentials: {exc}", "error")
            return redirect(url_for("auth.login"))

        if not result.user:
            flash("Invalid email or password.", "error")
            return redirect(url_for("auth.login"))

        role = "student"
        try:
            prof = (
                supabase.table("profiles")
                .select("role")
                .eq("id", result.user.id)
                .execute()
            )
            if prof.data:
                role = prof.data[0].get("role", "student")
            else:
                if supabase_admin:
                    try:
                        supabase_admin.table("profiles").upsert({
                            "id": result.user.id,
                            "email": email,
                            "role": "student",
                        }).execute()
                    except Exception as exc:
                        print(f"[PROFILE CREATE FAIL] login user={result.user.id} error={exc}")
        except Exception:
            pass

        session["user_email"] = email
        session["user_id"] = result.user.id
        session["role"] = role

        if role == "employee":
            return redirect(url_for("employee.employee_dashboard"))
        elif role == "student":
            return redirect(url_for("student.student_dashboard"))
        return redirect(url_for("public.home"))

    return render_template("login.html")


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        full_name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if email == ADMIN_EMAIL:
            flash("This email is reserved.", "error")
            return redirect(url_for("auth.signup"))

        if not supabase:
            flash("Supabase isn't configured.", "error")
            return redirect(url_for("auth.signup"))

        try:
            result = supabase.auth.sign_up({
                "email": email,
                "password": password,
                "options": {"data": {"full_name": full_name}},
            })
        except Exception as exc:
            flash(f"Could not sign up: {exc}", "error")
            return redirect(url_for("auth.signup"))

        user = result.user
        if user and supabase_admin:
            try:
                supabase_admin.table("profiles").upsert({
                    "id": user.id,
                    "full_name": full_name,
                    "email": email,
                    "role": "student",
                }).execute()
            except Exception as exc:
                print(f"[PROFILE CREATE FAIL] signup user={user.id} error={exc}")

        flash("Account created! Check your email to confirm, then log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("signup.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("public.home"))


@bp.route("/auth/google")
def auth_google():
    if not SUPABASE_URL or not SUPABASE_KEY:
        flash("Supabase isn't configured.", "error")
        return redirect(url_for("auth.login"))

    verifier, challenge = _generate_pkce()
    session.permanent = True

    next_param = request.args.get("next", "")
    if next_param.startswith("/"):
        session["oauth_next"] = next_param
    else:
        session["oauth_next"] = url_for("employee.employee_dashboard")

    callback_url = url_for("auth.auth_callback", _external=True)

    params = {
        "provider": "google",
        "redirect_to": callback_url,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    qs = urllib.parse.urlencode(params)
    session["oauth_verifier"] = verifier
    return redirect(f"{SUPABASE_URL}/auth/v1/authorize?{qs}")


@bp.route("/auth/callback")
def auth_callback():
    oauth_error = request.args.get("error")
    oauth_error_desc = request.args.get("error_description", "")
    if oauth_error:
        flash(f"Sign-in failed: {oauth_error_desc or oauth_error}", "error")
        return redirect(url_for("auth.login"))

    code = request.args.get("code")
    verifier = session.pop("oauth_verifier", None)

    if not code or not verifier:
        flash("Sign-in failed — session expired or denied.", "error")
        return redirect(url_for("auth.login"))

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
        return redirect(url_for("auth.login"))

    user = data.get("user")
    if not user:
        flash("Could not retrieve user info.", "error")
        return redirect(url_for("auth.login"))

    user_id = user.get("id")
    email = user.get("email", "").lower()
    meta = user.get("user_metadata") or {}
    full_name = meta.get("full_name") or meta.get("name", "")

    role = "student"
    profile_exists = False
    try:
        prof = (
            supabase.table("profiles")
            .select("role")
            .eq("id", user_id)
            .execute()
        )
        if prof.data:
            role = prof.data[0].get("role", "student")
            profile_exists = True
    except Exception:
        pass

    if not profile_exists:
        if supabase_admin:
            try:
                supabase_admin.table("profiles").upsert({
                    "id": user_id,
                    "full_name": full_name,
                    "email": email,
                    "role": "student",
                }).execute()
            except Exception as exc:
                print(f"[PROFILE CREATE FAIL] user={user_id} error={exc}")
                flash("Logged in, but profile sync had an issue.", "warning")
        else:
            print("[PROFILE CREATE FAIL] supabase_admin is None")
            flash("Logged in, but profile sync is unavailable.", "warning")

    if supabase_admin:
        try:
            supabase_admin.table("profiles").update({
                "email": email,
                "full_name": full_name,
            }).eq("id", user_id).execute()
        except Exception:
            pass

    session["user_email"] = email
    session["user_id"] = user_id
    session["role"] = role

    flash("Signed in with Google.", "success")

    next_url = session.pop("oauth_next", None)
    if next_url:
        return redirect(next_url)

    if role == "employee":
        return redirect(url_for("employee.employee_dashboard"))
    elif role == "student":
        return redirect(url_for("student.student_dashboard"))
    return redirect(url_for("public.home"))