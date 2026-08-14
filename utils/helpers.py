from flask import session
from extensions import supabase, supabase_admin


def _allowed_image(filename: str) -> bool:
    from config import ALLOWED_IMAGE_EXTENSIONS
    return (
        bool(filename)
        and "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS
    )


def _get_current_role(user_id: str | None) -> str:
    if not user_id:
        return session.get("role", "student")

    client = supabase_admin or supabase
    if client:
        try:
            prof = (
                client.table("profiles")
                .select("role")
                .eq("id", user_id)
                .execute()
            )
            if prof.data:
                return prof.data[0].get("role", "student")
        except Exception:
            pass

    return session.get("role", "student")


def _profile_complete(user_id: str | None) -> bool:
    """
    Return True if the student has a username set.
    Uses session cache to prevent infinite loops after successful save.
    """
    # 1. Session cache: if we just saved the profile, trust it
    if session.get("profile_complete"):
        return True

    if not user_id:
        return False

    # 2. Use service role only — anon key cannot read through RLS in Flask
    client = supabase_admin
    if not client:
        # No service role = cannot verify, so let user through to avoid trap
        print("[PROFILE CHECK] supabase_admin is None — skipping gate")
        return True

    try:
        res = client.table("profiles").select("username").eq("id", user_id).execute()
        if res.data and len(res.data) > 0:
            has_username = bool(res.data[0].get("username") and res.data[0].get("username").strip())
            if has_username:
                session["profile_complete"] = True
            return has_username
        return False
    except Exception as exc:
        print(f"[PROFILE CHECK] exception: {exc}")
        # On error, let user through rather than trapping them
        return True

def _allowed_assignment(filename: str) -> bool:
    from config import ALLOWED_ASSIGNMENT_EXTENSIONS
    return (
        bool(filename)
        and "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_ASSIGNMENT_EXTENSIONS
    )