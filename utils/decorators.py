from functools import wraps
from flask import session, flash, redirect, url_for


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_email"):
            flash("Please log in to continue.", "error")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_email"):
            flash("Please log in to continue.", "error")
            return redirect(url_for("auth.login"))

        user_id = session.get("user_id")

        if user_id is None:
            # Env-based admin login (ADMIN_EMAIL/ADMIN_PASSWORD): there is no
            # profiles row for this account, so session["role"] (set at login
            # to "admin") is the only source of truth here.
            if session.get("role") != "admin":
                flash("Admins only.", "error")
                return redirect(url_for("auth.login"))
            return view(*args, **kwargs)

        # Real Supabase user: re-check the role from the database on every
        # admin request, so a role change takes effect immediately instead
        # of only after the user logs out and back in.
        from utils.helpers import _get_current_role
        role = _get_current_role(user_id)
        session["role"] = role

        if role != "admin":
            flash("Admins only.", "error")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped