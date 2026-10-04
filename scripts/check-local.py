"""Exercise the running local service; remove only this probe's temporary records."""
import json
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:9090"
parsed = urlparse(base)
if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.scheme != "http":
    raise SystemExit("This probe only accepts a local HTTP service.")
credentials = json.loads((ROOT / "data" / "local-access.json").read_text())
session = requests.Session()
session.trust_env = False
checks = []


def request(method, path, status=200, **kwargs):
    response = session.request(method, base + path, timeout=30, **kwargs)
    assert response.status_code == status, f"{method} {path}: {response.status_code}"
    return response


assert request("GET", "/health").json()["status"] == "healthy"
checks.append("health")
login = request("GET", "/login/")
csrf = BeautifulSoup(login.text, "html.parser").select_one('[name="csrfmiddlewaretoken"]')["value"]
page = request("POST", "/login/", data={**credentials, "csrfmiddlewaretoken": csrf})
assert urlparse(page.url).path == "/research/"
session.headers["X-CSRFToken"] = session.cookies["ld_csrftoken"]
checks.append("session_login")
assert requests.get(base + "/api/bookmarks/", timeout=10).status_code == 401
checks.append("unauthenticated_api_rejected")
nonce = uuid.uuid4().hex
tag = f"local-probe-{nonce}"
title = f"Local runtime probe {nonce}"
bookmark_id = None
tag_id = None
try:
    bookmark = request("POST", "/api/bookmarks/?disable_scraping&disable_html_snapshot", status=201,
                       json={"url": f"https://example.com/?local-probe={nonce}", "title": title,
                             "notes": "本地运行验证", "tag_names": [tag], "unread": True}).json()
    bookmark_id = bookmark["id"]
    checks.append("create_bookmark_with_tag_and_notes")
    for item in request("GET", "/api/tags/").json()["results"]:
        if item["name"] == tag:
            tag_id = item["id"]
    request("PATCH", f"/api/bookmarks/{bookmark_id}/", json={"description": "Edited by local probe"})
    assert request("GET", f"/api/bookmarks/{bookmark_id}/").json()["description"] == "Edited by local probe"
    checks.append("edit_and_read_bookmark")
    results = request("GET", "/api/bookmarks/", params={"q": nonce}).json()["results"]
    assert any(item["id"] == bookmark_id for item in results)
    checks.append("search_bookmark")
    content = "linkding 本地附件上传与下载验证\n".encode()
    asset = request("POST", f"/api/bookmarks/{bookmark_id}/assets/upload/", status=201,
                    files={"file": ("local-probe.txt", content, "text/plain")}).json()
    downloaded = request("GET", f"/api/bookmarks/{bookmark_id}/assets/{asset['id']}/download/")
    assert downloaded.content == content
    checks.append("attachment_upload_download_content_match")
    exported = request("GET", "/settings/export")
    assert "attachment" in exported.headers["Content-Disposition"]
    assert nonce in exported.text and tag in exported.text
    (ROOT / "data" / "local-smoke-export.html").write_bytes(exported.content)
    checks.append("netscape_html_export")
finally:
    if bookmark_id is not None:
        request("DELETE", f"/api/bookmarks/{bookmark_id}/", status=204)
        checks.append("temporary_bookmark_cleanup")
    if tag_id is not None:
        request("DELETE", f"/api/tags/{tag_id}/", status=204)
report = {"base_url": base, "checks": checks, "status": "passed"}
(ROOT / "data" / "local-smoke-result.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
