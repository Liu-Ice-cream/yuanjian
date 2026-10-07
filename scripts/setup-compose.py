"""Create private Compose credentials once, without changing an existing .env."""

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
destination = ROOT / ".env"
content = (ROOT / ".env.sample").read_text(encoding="utf-8")
content = content.replace("LD_SUPERUSER_NAME=\n", "LD_SUPERUSER_NAME=localadmin\n")
content = content.replace(
    "LD_SUPERUSER_PASSWORD=\n",
    f"LD_SUPERUSER_PASSWORD={secrets.token_urlsafe(24)}\n",
)
try:
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print("Existing .env retained. Account credentials unchanged.")
else:
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
        target.write(content)
    print("Compose configured. Read LD_SUPERUSER_NAME/PASSWORD in your local .env.")
    print("Keep .env private. Run: docker compose up --build -d --wait")
