"""A local-only task to verify the separate consumer executes queued work."""
from huey.contrib.djhuey import task
from pathlib import Path


@task()
def local_runtime_probe(nonce=""):
    probe_file = Path(__file__).resolve().parents[1] / "data" / "local-worker-probe.txt"
    probe_file.write_text(nonce, encoding="utf-8")
