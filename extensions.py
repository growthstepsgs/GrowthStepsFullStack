from supabase import create_client, Client
import config

# ─────────────────────────────────────────────────────────────────────────
# supabase_admin — safe to share as one global client.
# It uses the service-role key and never calls .auth.sign_in_with_password()
# or holds a per-user session, so there is nothing for concurrent requests
# to leak between users. All RLS-sensitive reads/writes that need to be
# reliable (role lookups, admin writes, etc.) should go through this.
# ─────────────────────────────────────────────────────────────────────────
supabase_admin: Client | None = None

if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
    supabase_admin = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
else:
    print("🚨 CRITICAL: SUPABASE_SERVICE_KEY is missing. Profile saves will fail.")


# ─────────────────────────────────────────────────────────────────────────
# supabase — a plain anon-key client for ANONYMOUS reads only
# (e.g. public pages reading rows that don't depend on who's logged in).
#
# IMPORTANT: never call .auth.sign_in_with_password(), .auth.sign_up(), or
# anything else that attaches a user session to THIS object. It's a single
# instance shared by every request; attaching a session to it would leak
# one user's identity into other users' concurrent requests. Use
# get_auth_client() below for any login/signup/password flow instead.
# ─────────────────────────────────────────────────────────────────────────
supabase: Client | None = None

if config.SUPABASE_URL and config.SUPABASE_KEY:
    supabase = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)


def get_auth_client() -> Client | None:
    """Returns a brand-new Supabase client, scoped to a single request.

    Use this anywhere a user is signing in, signing up, or any flow that
    calls supabase.auth.* and attaches a session — never reuse the shared
    `supabase` singleton for that, since its session would then be visible
    to every other request sharing the process.

    Example:
        client = get_auth_client()
        result = client.auth.sign_in_with_password({"email": email, "password": password})
    """
    if not (config.SUPABASE_URL and config.SUPABASE_KEY):
        return None
    return create_client(config.SUPABASE_URL, config.SUPABASE_KEY)