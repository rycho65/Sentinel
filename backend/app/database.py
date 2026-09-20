"""Supabase/Postgres connectivity. Reads credentials from backend/.env
(never committed - see .gitignore) via python-dotenv.

    get_supabase()   -> supabase-py client, for the Supabase REST/auth API
    get_connection() -> raw psycopg2 connection, for direct SQL over DATABASE_URL

Nothing in the app calls these yet - the simulation is still fully in-memory
per request. Wire a call site in main.py once there's something to persist
(e.g. saving a run's timeline/metrics)."""

import os

import psycopg2
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

_supabase_client: Client | None = None


def get_supabase() -> Client:
    global _supabase_client
    if _supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL / SUPABASE_KEY not set - check backend/.env")
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client


def get_connection():
    """A new raw psycopg2 connection over DATABASE_URL. Caller is
    responsible for closing it (or use it as a context manager)."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set - check backend/.env")
    return psycopg2.connect(DATABASE_URL)
