from supabase import create_client
from backend.config import SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY

# Public read client — RLS is active; returns only publicly visible data
anon_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# Service client — bypasses RLS; used by scrapers and admin write operations only
service_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
