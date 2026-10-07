"""Restore Windows system paths before loading network modules in a service."""

import argparse
import os
import runpy
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("service", choices=["web", "worker"])
parser.add_argument("--system-root", required=True)
parser.add_argument("--port", type=int, default=9090)
args = parser.parse_args()
# Start-Process -UseNewEnvironment omits process-only system variables on
# some Windows installations. Winsock requires a valid SystemRoot.
os.environ["SYSTEMROOT"] = args.system_root
os.environ["WINDIR"] = args.system_root
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
if args.service == "web":
    sys.argv = [
        "manage.py",
        "runserver",
        f"127.0.0.1:{args.port}",
        "--noreload",
        "--settings=local_settings",
    ]
    runpy.run_path(str(root / "manage.py"), run_name="__main__")
else:
    sys.argv = ["local_worker.py"]
    runpy.run_path(str(root / "scripts" / "local_worker.py"), run_name="__main__")
