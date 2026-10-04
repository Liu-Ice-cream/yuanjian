"""Verify that the local consumer completes a task, rather than just stays alive."""
import os
import sys
import secrets
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DJANGO_SETTINGS_MODULE"] = "local_settings"
import django

django.setup()
from huey.contrib.djhuey import HUEY
from local_queue_probe import local_runtime_probe

assert not HUEY.immediate, "Queue verification requires a separate consumer."
nonce = secrets.token_hex(16)
probe_file = Path(__file__).resolve().parents[1] / "data" / "local-worker-probe.txt"
local_runtime_probe(nonce)
deadline = time.monotonic() + 25
while time.monotonic() < deadline:
    if probe_file.exists() and probe_file.read_text(encoding="utf-8") == nonce:
        break
    time.sleep(0.25)
else:
    raise RuntimeError("The consumer did not execute the probe within 25 seconds.")
print("Separate background worker executed the queue probe.")
