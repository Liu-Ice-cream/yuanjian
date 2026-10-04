"""Local Windows development settings. Copied to ignored local_settings.py."""
from bookmarks.settings.dev import *  # noqa: F403
from pathlib import Path

SECRET_KEY = (Path(BASE_DIR) / "data" / "local-secret.txt").read_text().strip()  # noqa: F405
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
# Optional SingleFile/Chromium snapshot tooling is not installed by local setup.
LD_ENABLE_SNAPSHOTS = False
