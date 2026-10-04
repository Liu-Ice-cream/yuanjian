"""Run Huey's thread consumer on Windows without the CLI's Python 3.14 fork call."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DJANGO_SETTINGS_MODULE"] = "local_settings"
import django

django.setup()
from django.conf import settings
from django.utils.module_loading import autodiscover_modules
from huey.contrib.djhuey import HUEY
import local_queue_probe  # noqa: F401

autodiscover_modules("tasks")
options = dict(settings.HUEY.get("consumer", {}))
options["worker_type"] = "thread"
HUEY.create_consumer(**options).run()
