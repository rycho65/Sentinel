"""Supabase connectivity. Reads credentials from backend/.env (never
committed - see .gitignore) via python-dotenv.

    get_supabase() -> supabase-py client, for the Supabase REST API

Used by app/db_sync.py to mirror live-product state (see
backend/supabase/schema.sql for the tables)."""

import os

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

_supabase_client: Client | None = None


def get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL / SUPABASE_KEY not set - check backend/.env")
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client
