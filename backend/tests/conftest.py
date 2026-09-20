import pathlib
import sys

# Let tests `import app.xxx` regardless of the cwd pytest is invoked from.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
