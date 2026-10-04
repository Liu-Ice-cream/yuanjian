"""Initialize local directories and an administrator without exposing secrets."""
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"
for folder in (DATA, DATA / "assets", DATA / "favicons", DATA / "previews"):
    folder.mkdir(parents=True, exist_ok=True)
secret_file = DATA / "local-secret.txt"
if not secret_file.exists():
    secret_file.write_text(secrets.token_urlsafe(48), encoding="utf-8")
if "--prepare" in sys.argv:
    raise SystemExit(0)

os.environ["DJANGO_SETTINGS_MODULE"] = "local_settings"
import django

django.setup()
from django.contrib.auth.models import User

username = "localadmin"
if User.objects.filter(username=username).exists():
    print("Existing localadmin retained; password unchanged.")
else:
    password = secrets.token_urlsafe(18)
    User.objects.create_superuser(username=username, password=password)
    (DATA / "local-access.json").write_text(
        json.dumps({"username": username, "password": password}, indent=2),
        encoding="utf-8",
    )
    print("Local administrator created. Credentials: data/local-access.json")
