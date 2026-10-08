"""Shared helpers: HTTP, hashing, the versions.json manifest, the run report."""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "versions.json"


def vkey(version):
    return tuple(int(part) for part in version.split("."))


def load():
    return json.loads(MANIFEST.read_text())


def save(data):
    for info in data["apps"].values():
        info["versions"] = dict(sorted(info["versions"].items(), key=lambda kv: vkey(kv[0])))
    MANIFEST.write_text(json.dumps(data, indent=2) + "\n")


def gh_token():
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()


def request(url, method="GET", headers=None, data=None, timeout=600):
    """Open url; returns the response. Raises urllib.error.HTTPError on 4xx/5xx."""
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
    return urllib.request.urlopen(req, timeout=timeout)


def get_json(url, headers=None):
    """GET url as JSON; None on 404."""
    try:
        with request(url, headers=headers) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        raise


def get_pages(url, headers=None):
    """GET a paginated JSON list (per_page=100); None on 404."""
    items, page = [], 1
    sep = "&" if "?" in url else "?"
    while True:
        batch = get_json(f"{url}{sep}per_page=100&page={page}", headers)
        if batch is None:
            return None if page == 1 else items
        items += batch
        if len(batch) < 100:
            return items
        page += 1


def github_headers():
    return {"Authorization": f"Bearer {gh_token()}", "Accept": "application/vnd.github+json"}


def download(url, dest):
    """Stream url to dest. Raises on HTTP errors."""
    with request(url) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out, 1 << 20)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def to_sri(hexdigest):
    return "sha256-" + base64.b64encode(bytes.fromhex(hexdigest)).decode()


def from_sri(sri):
    return base64.b64decode(sri.removeprefix("sha256-")).hex()


class Report:
    """Collects what a run did; failures make the workflow fail (and email)."""

    def __init__(self):
        self.lines, self.failures = [], []

    def info(self, msg):
        print(msg, flush=True)
        self.lines.append(msg)

    def fail(self, msg):
        print(f"FAIL: {msg}", file=sys.stderr, flush=True)
        self.failures.append(msg)

    def write(self):
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if not path:
            return
        with open(path, "a") as f:
            f.write("## ArtCraft update\n\n")
            f.writelines(f"- {line}\n" for line in self.lines or ["nothing new"])
            if self.failures:
                f.write("\n### Failures\n\n")
                f.writelines(f"- {line}\n" for line in self.failures)
