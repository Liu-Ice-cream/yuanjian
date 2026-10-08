"""Check that local data and the maintainer's personal email are not published."""

import subprocess


def git(*args):
    return subprocess.check_output(["git", *args]).decode("utf-8")


private_directories = {
    "data",
    "docker-data",
    "project-notes",
    ".tools",
    ".codex",
    ".agents",
    ".venv",
    "node_modules",
}
private_filenames = {
    ".env",
    "local_settings.py",
    "local-access.json",
    "local-secret.txt",
}
for name in git("ls-files").splitlines():
    parts = name.split("/")
    if parts[0] in private_directories or parts[-1] in private_filenames:
        raise SystemExit(f"Local-only file tracked: {name}")

baseline = "24b5ad6cc9bde497b5d1b1e86aed5a2fb7d25c2f"
records = git("log", "--all", f"^{baseline}", "--format=%an%x00%ae%x00%cn%x00%ce")
for record in records.splitlines():
    author, author_email, committer, committer_email = record.split("\0")
    for name, email in [(author, author_email), (committer, committer_email)]:
        if name == "Liu-Ice-cream" and not email.endswith("@users.noreply.github.com"):
            raise SystemExit("Maintainer commit must use a GitHub privacy email.")
print(
    "Public-tree privacy boundaries passed: local-only files excluded and maintainer privacy email used."
)
