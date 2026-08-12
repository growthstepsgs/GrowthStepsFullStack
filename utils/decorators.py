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
        if session.get("role") != "admin":
            flash("Admins only.", "error")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped