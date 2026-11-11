import os
import tempfile

# must run before app.py is imported so tests never touch the real data/ folder
os.environ["CCDA_DATA_DIR"] = tempfile.mkdtemp(prefix="ccda-test-")
