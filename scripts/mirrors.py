"""Keep every manifest version mirrored on GitHub releases and GitLab packages.

GitHub: one release per app, tag `mirror-<app>`, every version as an asset.
GitLab: generic package `<app>`, one package version per app version.
Both also carry upstream's license files (MIT, Apache-2.0, NOTICE).
"""

import subprocess
import tempfile
import urllib.error
import urllib.parse
from pathlib import Path

import common

LICENSE_FILES = ["LICENSE-MIT", "LICENSE-APACHE", "NOTICE"]


def gitlab_api(project):
    return f"https://gitlab.com/api/v4/projects/{urllib.parse.quote(project, safe='')}"


def urls(data, app, version):
    """Download URLs for one version: upstream, GitHub mirror, GitLab mirror."""
    info, entry, mirrors = data["apps"][app], data["apps"][app]["versions"][version], data["mirrors"]
    return [
        f"https://github.com/{info['repo']}/releases/download/{entry['tag']}/{entry['file']}",
        f"https://github.com/{mirrors['github']}/releases/download/mirror-{app}/{entry['file']}",
        f"{gitlab_api(mirrors['gitlab'])}/packages/generic/{app}/{version}/{entry['file']}",
    ]


def fetch_verified(candidates, sri, dest):
    """Download from the first candidate URL whose file matches sri."""
    for url in candidates:
        try:
            common.download(url, dest)
        except (urllib.error.URLError, OSError):
            continue
        if common.sha256_file(dest) == common.from_sri(sri):
            return dest
    raise RuntimeError(f"no source has a copy matching {sri}")


def license_files(data, app, workdir):
    """Fetch upstream license files (or from the GitLab source mirror)."""
    repo = data["apps"][app]["repo"]
    mirror = f"{data['mirrors']['gitlabSources']}/{repo.split('/')[1]}-mirror"
    # The authenticated API, not raw.githubusercontent.com, which rate-limits
    # the shared Actions runner IPs.
    api = {**common.github_headers(), "Accept": "application/vnd.github.raw"}
    found = []
    for name in LICENSE_FILES:
        dest = Path(workdir) / name
        for url, headers in ((f"https://api.github.com/repos/{repo}/contents/{name}", api),
                             (f"https://gitlab.com/{mirror}/-/raw/HEAD/{name}", None)):
            try:
                common.download(url, dest, headers)
                found.append(dest)
                break
            except urllib.error.URLError:
                continue
    return found


def github_assets(repo, app):
    """Asset names on the app's mirror release; None if the release is missing."""
    rel = common.get_json(f"https://api.github.com/repos/{repo}/releases/tags/mirror-{app}", common.github_headers())
    if rel is None:
        return None
    assets = common.get_pages(f"https://api.github.com/repos/{repo}/releases/{rel['id']}/assets", common.github_headers())
    return {a["name"] for a in assets}


def github_create(data, app, licenses):
    info, repo = data["apps"][app], data["mirrors"]["github"]
    notes = (f"Mirror of every {info['title']} release from https://github.com/{info['repo']}, "
             "byte-identical (checked against upstream's published sha256).\n\n"
             f"{info['title']} is licensed MIT OR Apache-2.0 by its authors; the license files are attached. "
             "Not affiliated with the upstream project.")
    subprocess.run(["gh", "release", "create", f"mirror-{app}", "-R", repo, "--title", f"{info['title']} mirror",
                    "--notes", notes, "--latest=false", *map(str, licenses)], check=True)


def gitlab_versions(project, token):
    """{(app, version)} already uploaded to GitLab's generic package registry."""
    pkgs = common.get_pages(f"{gitlab_api(project)}/packages?package_type=generic", {"PRIVATE-TOKEN": token})
    return {(p["name"], p["version"]) for p in pkgs or []}


def gitlab_upload(project, token, app, version, path):
    url = f"{gitlab_api(project)}/packages/generic/{app}/{version}/{path.name}"
    with open(path, "rb") as f:
        headers = {"PRIVATE-TOKEN": token, "Content-Length": str(path.stat().st_size)}
        common.request(url, method="PUT", headers=headers, data=f).close()


def ensure(data, apps, token, report):
    """Upload whatever any mirror lacks, for every version of every app."""
    gh_repo, gl_project = data["mirrors"]["github"], data["mirrors"]["gitlab"]
    if not token:
        report.fail("GITLAB_TOKEN not set: GitLab mirror skipped")
    on_gitlab = gitlab_versions(gl_project, token) if token else set()
    for app in apps:
        with tempfile.TemporaryDirectory() as tmp:
            licenses = license_files(data, app, tmp)
            if not licenses:
                report.fail(f"{app}: no license files found upstream or on the source mirror")
            on_github = github_assets(gh_repo, app)
            if on_github is None:
                github_create(data, app, licenses)
                on_github = {p.name for p in licenses}
            missing = [str(p) for p in licenses if p.name not in on_github]
            if missing:
                subprocess.run(["gh", "release", "upload", f"mirror-{app}", *missing, "-R", gh_repo, "--clobber"],
                               check=True)
                report.info(f"attached license files to mirror-{app}")
            for version, entry in data["apps"][app]["versions"].items():
                need_gh = entry["file"] not in on_github
                need_gl = bool(token) and (app, version) not in on_gitlab
                if not (need_gh or need_gl):
                    continue
                try:
                    path = fetch_verified(urls(data, app, version), entry["hash"], Path(tmp) / entry["file"])
                    if need_gh:
                        subprocess.run(["gh", "release", "upload", f"mirror-{app}", str(path), "-R", gh_repo,
                                        "--clobber"], check=True)
                        report.info(f"mirrored {entry['file']} to GitHub")
                    if need_gl:
                        for f in [path, *licenses]:
                            gitlab_upload(gl_project, token, app, version, f)
                        report.info(f"mirrored {entry['file']} to GitLab")
                    path.unlink()
                except Exception as err:  # one bad file must not stop the rest
                    report.fail(f"mirroring {app} {version}: {err}")
