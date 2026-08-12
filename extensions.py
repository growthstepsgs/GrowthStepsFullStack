from supabase import create_client, Client
import config

supabase: Client | None = None
supabase_admin: Client | None = None

if config.SUPABASE_URL and config.SUPABASE_KEY:
    supabase = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
    supabase_admin = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
elif supabase:
    supabase_admin = supabase