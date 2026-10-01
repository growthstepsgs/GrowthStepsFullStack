import secrets
import hashlib
import base64
import urllib.parse
import httpx
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash
)
from extensions import supabase, supabase_admin, get_auth_client
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


def _safe_next():
    """Return (and clear) a saved same-site path to send the user back to after login.
    Set by routes/jobs.py when a logged-out visitor hits /jobs. Only local paths are allowed."""
    n = session.pop("next_url", None)
    if n and n.startswith("/") and not n.startswith("//") and "\\" not in n:
        return n
    return None


@bp.route("/login", methods=["GET", "POST"])
def login():
    # Already logged in? Go to dashboard.
    if "user_id" in session:
        role = session.get("role")
        if role == "admin":
            return redirect(url_for("admin.admin_dashboard"))
        elif role == "employee":
            return redirect(url_for("employee.employee_dashboard"))
        elif role == "student":
            return redirect(url_for("student.student_dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
            session["user_email"] = email
            session["user_id"] = None
            session["role"] = "admin"
            return redirect(url_for("admin.admin_dashboard"))

        # A fresh client per login attempt — never reuse a shared singleton for
        # .auth.sign_in_with_password(), or one user's session could leak into
        # another user's concurrent request.
        auth_client = get_auth_client()
        if not auth_client:
            flash("Supabase isn't configured.", "error")
            return redirect(url_for("auth.login"))

        try:
            result = auth_client.auth.sign_in_with_password(
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
            # IMPORTANT: read the role via supabase_admin (service role, bypasses
            # RLS), not the plain `supabase` client. Using the RLS-gated client
            # here was the actual bug that caused admin roles to reset: if that
            # select ever came back empty (RLS/session timing), the old code
            # assumed the profile didn't exist and upserted role="student",
            # silently overwriting an admin role that had just been set.
            role_client = supabase_admin or supabase
            prof = (
                role_client.table("profiles")
                .select("role")
                .eq("id", result.user.id)
                .execute()
            )
            if prof.data:
                role = prof.data[0].get("role", "student")
            elif supabase_admin:
                # Profile genuinely doesn't exist (confirmed via the admin
                # client, not the RLS-gated one) -> safe to create as new.
                try:
                    supabase_admin.table("profiles").upsert({
                        "id": result.user.id,
                        "email": email,
                        "role": "student",
                    }).execute()
                except Exception as exc:
                    print(f"[PROFILE CREATE FAIL] login user={result.user.id} error={exc}")
        except Exception as exc:
            print(f"[ROLE LOOKUP FAIL] login user={result.user.id} error={exc}")

        session["user_email"] = email
        session["user_id"] = result.user.id
        session["role"] = role

        # Send the user back to the page they originally wanted (e.g. /jobs?q=python)
        next_url = _safe_next()
        if next_url:
            return redirect(next_url)

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

        # Fresh client for the signup attempt itself (sign_up attaches a
        # session to whatever client makes the call) — never the shared one.
        auth_client = get_auth_client()
        if not auth_client:
            flash("Supabase isn't configured.", "error")
            return redirect(url_for("auth.signup"))

        try:
            result = auth_client.auth.sign_up({
                "email": email,
                "password": password,
                "options": {
                    "data": {
                        "full_name": full_name
                    }
                },
            })

        except Exception as exc:
            msg = str(exc)

            if (
                "already registered" in msg.lower()
                or "already been registered" in msg.lower()
            ):
                flash(
                    "An account with this email already exists — please log in.",
                    "error"
                )
                return redirect(url_for("auth.login"))

            flash(f"Could not sign up: {exc}", "error")
            return redirect(url_for("auth.signup"))

        user = result.user

        # Create/update profile
        if user and supabase_admin:
            try:
                supabase_admin.table("profiles").upsert({
                    "id": user.id,
                    "full_name": full_name,
                    "email": email,
                    "role": "student",
                }).execute()

            except Exception as exc:
                print(
                    f"[PROFILE CREATE FAIL] "
                    f"signup user={user.id} error={exc}"
                )

        # ─────────────────────────────────────────────
        # CASE 1: Supabase returned a session directly
        # ─────────────────────────────────────────────
        if user and result.session:
            session["user_email"] = email
            session["user_id"] = user.id
            session["role"] = "student"

            flash("Welcome to Growth Steps!", "success")
            return redirect(url_for("student.student_dashboard"))

        # ─────────────────────────────────────────────
        # CASE 2: User created but no session
        # Auto-confirm email and login
        # ─────────────────────────────────────────────
        if user and not result.session:

            # Confirm email using Supabase Admin API
            if supabase_admin:
                try:
                    supabase_admin.auth.admin.update_user_by_id(
                        user.id,
                        {
                            "email_confirm": True
                        }
                    )

                except Exception as exc:
                    print(
                        f"[AUTO-CONFIRM FAIL] "
                        f"user={user.id} error={exc}"
                    )

            # Try to create a session immediately — fresh client again, same
            # reasoning as above (this is a second, separate sign-in attempt).
            try:
                login_client = get_auth_client() or auth_client
                login_res = login_client.auth.sign_in_with_password({
                    "email": email,
                    "password": password
                })

                if login_res.user and login_res.session:
                    session["user_email"] = email
                    session["user_id"] = user.id
                    session["role"] = "student"

                    flash("Welcome to Growth Steps!", "success")
                    return redirect(
                        url_for("student.student_dashboard")
                    )

                flash(
                    "Account created but automatic login failed. "
                    "Please log in.",
                    "error"
                )
                return redirect(url_for("auth.login"))

            except Exception as exc:
                print(
                    f"[AUTO-LOGIN FAIL] "
                    f"user={user.id} error={exc}"
                )

                flash(
                    "Account created but automatic login failed. "
                    "Please log in.",
                    "error"
                )
                return redirect(url_for("auth.login"))

        # ─────────────────────────────────────────────
        # Unexpected case
        # ─────────────────────────────────────────────
        flash(
            "Account created. Please log in.",
            "success"
        )
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
    if next_param.startswith("/") and not next_param.startswith("//"):
        session["oauth_next"] = next_param
    else:
        # falls back to the page saved by /jobs (if any), otherwise the original default
        session["oauth_next"] = _safe_next() or url_for("employee.employee_dashboard")

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
        # Same fix as login(): read via supabase_admin (bypasses RLS) so an
        # empty result is never mistaken for "no profile yet" and used to
        # reset an existing role.
        role_client = supabase_admin or supabase
        prof = (
            role_client.table("profiles")
            .select("role")
            .eq("id", user_id)
            .execute()
        )
        if prof.data:
            role = prof.data[0].get("role", "student")
            profile_exists = True
    except Exception as exc:
        print(f"[ROLE LOOKUP FAIL] google user={user_id} error={exc}")

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