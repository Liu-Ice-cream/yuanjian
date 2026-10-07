"""Acceptance probe for a disposable, freshly installed CI environment only."""

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("phase", choices=["seed", "verify"])
parser.add_argument("--settings", default="bookmarks.settings")
parser.add_argument("--base", default="http://127.0.0.1:9090")
parser.add_argument("--container", action="store_true")
args = parser.parse_args()
if urlparse(args.base).hostname not in {"127.0.0.1", "localhost"}:
    raise SystemExit("Only a disposable localhost installation is accepted.")
os.environ["DJANGO_SETTINGS_MODULE"] = args.settings
import django  # noqa: E402

django.setup()
import requests  # noqa: E402, TID251
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402

from bookmarks.models import Bookmark  # noqa: E402
from research.models import (  # noqa: E402
    ResearchExcerpt,
    ResearchGroup,
    ResearchItem,
    ResearchPlacement,
    ResearchProject,
)

state_file = ROOT / "data" / "installation-probe.json"
credentials = (
    {
        "username": os.environ["LD_SUPERUSER_NAME"],
        "password": os.environ["LD_SUPERUSER_PASSWORD"],
    }
    if args.container
    else json.loads((ROOT / "data" / "local-access.json").read_text())
)
session = requests.Session()
session.trust_env = False


def get(path):
    response = session.get(args.base + path, timeout=30)
    assert response.status_code == 200, f"GET {path}: {response.status_code}"
    return response


def post(path, payload):
    csrf = session.cookies["ld_csrftoken"]
    response = session.post(
        args.base + path,
        data={**payload, "csrfmiddlewaretoken": csrf},
        headers={"Referer": args.base + path},
        timeout=30,
        allow_redirects=False,
    )
    assert response.status_code == 302, f"POST {path}: {response.status_code}"
    return response


assert get("/health").json()["status"] == "healthy"
if args.container:
    assert not settings.DEBUG, "Container must use production settings."
login = get("/login/")
for asset in re.findall(r'(?:src|href)="(/static/[^"?]+)', login.text):
    assert get(asset).content, f"Empty static asset: {asset}"
if args.container:
    expected_logo = (Path(settings.STATIC_ROOT) / "yuanjian.svg").read_bytes()
    for _ in range(20):
        assert get("/static/yuanjian.svg").content == expected_logo
assert post("/login/", credentials).headers["Location"] == "/research/"
assert "源笺 v" + settings.PRODUCT_VERSION in get("/research/").text
user = User.objects.get(username=credentials["username"])

if args.phase == "seed":
    # Never run a seeding probe against an existing user's installation.
    assert not state_file.exists(), "This installation was already seeded."
    assert User.objects.count() == 1 and not Bookmark.objects.exists()
    assert not ResearchProject.objects.exists()
    marker = "installation-" + uuid.uuid4().hex
    post("/research/projects/new", {"name": marker, "description": "安装验收课题"})
    project = ResearchProject.objects.get(owner=user, name=marker)
    post(
        "/research/materials/new",
        {
            "url": "https://example.com/?" + marker,
            "title": marker,
            "project": project.pk,
            "material_type": "paper",
            "reading_stage": "collected",
            "question": "能否完整保存并再次导出？",
            "conclusion": "安装与重启验收材料",
            "doi": "",
        },
    )
    bookmark = Bookmark.objects.get(owner=user, title=marker)
    post(
        f"/research/materials/{bookmark.pk}/excerpts/new",
        {
            "original_text": "公开预览验收摘录",
            "interpretation": "保留来源并复用",
            "locator": "验收第 1 段",
        },
    )
    excerpt = ResearchExcerpt.objects.get(bookmark=bookmark)
    post(f"/research/projects/{project.pk}/outline/groups/new", {"name": "安装验证"})
    group = ResearchGroup.objects.get(project=project)
    post(
        f"/research/projects/{project.pk}/outline/groups/{group.pk}/add",
        {
            "selected": excerpt.pk,
        },
    )
    post(
        f"/research/materials/{bookmark.pk}/paper",
        {
            "action": "save",
            "doi": "",
            "title": marker,
            "authors": "Example, Author",
            "year": "2026",
            "venue": "",
            "entry_type": "misc",
        },
    )
    state_file.write_text(
        json.dumps(
            {
                "marker": marker,
                "project": project.pk,
                "bookmark": bookmark.pk,
                "excerpt": excerpt.pk,
                "group": group.pk,
                "password_hash": user.password,
                "secret": settings.SECRET_KEY,
            }
        ),
        encoding="utf-8",
    )

state = json.loads(state_file.read_text(encoding="utf-8"))
assert user.password == state["password_hash"]
assert state["secret"] == settings.SECRET_KEY
bookmark = Bookmark.objects.get(pk=state["bookmark"], owner=user)
assert bookmark.title == state["marker"]
assert ResearchItem.objects.get(bookmark=bookmark).project_id == state["project"]
assert (
    ResearchPlacement.objects.get(group_id=state["group"]).excerpt_id
    == state["excerpt"]
)
assert (
    "公开预览验收摘录"
    in get(f"/research/projects/{state['project']}/outline/export").text
)
assert state["marker"] in get("/research/export").text
bib = get(f"/research/projects/{state['project']}/citations/export?scope=outline")
assert "attachment" in bib.headers["Content-Disposition"]
assert f"@misc{{yuanjian{bookmark.pk}," in bib.text
assert state["marker"] in bib.text and "2026" in bib.text
print(
    f"Installation {args.phase} passed: login, static assets, research, exports and retained data."
)
