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
    """Fetch the freshest role from Supabase profiles table."""
    if not user_id:
        return session.get("role", "student")

    client = supabase_admin or supabase
    if client:
        try:
            prof = (
                client.table("profiles")
                .select("role")
                .eq("id", user_id)
                .single()
                .execute()
            )
            if prof.data:
                return prof.data.get("role", "student")
        except Exception:
            pass

    return session.get("role", "student")