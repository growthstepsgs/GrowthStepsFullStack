from extensions import supabase_admin


def admin_db():
    """Reuses the service-role client you already create in extensions.py."""
    if supabase_admin is None:
        raise RuntimeError("SUPABASE_SERVICE_KEY is not configured")
    return supabase_admin