import os
import pathlib
import sys

# Let tests `import app.xxx` regardless of the cwd pytest is invoked from.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# Must be set before app.db_sync is ever imported (it reads this once, at
# import time) - the test suite must never touch the network or write real
# rows into whatever Supabase project backend/.env happens to point at.
os.environ["SENTINEL_DB_SYNC"] = "0"
