"""Mirror the upstream source repositories to GitLab (`<namespace>/<repo>-mirror`).

Pushes are additive and never forced: upstream deleting or rewriting history
does not propagate, so the mirror keeps what it already had.
"""

import base64
import os
import subprocess
import tempfile
import urllib.parse

import common
from mirrors import gitlab_api


def ensure_project(path, repo, token):
    """Create the public GitLab mirror project if missing."""
    if common.get_json(gitlab_api(path), {"PRIVATE-TOKEN": token}) is not None:
        return
    name = path.split("/")[1]
    body = urllib.parse.urlencode({
        "path": name,
        "name": name,
        "visibility": "public",
        "description": f"Read-only mirror of https://github.com/{repo} (MIT OR Apache-2.0). Not affiliated with upstream.",
    }).encode()
    headers = {"PRIVATE-TOKEN": token, "Content-Type": "application/x-www-form-urlencoded"}
    common.request("https://gitlab.com/api/v4/projects", method="POST", headers=headers, data=body).close()


def mirror(data, apps, token, report):
    if not token:
        return  # already reported by mirrors.ensure
    auth = base64.b64encode(f"oauth2:{token}".encode()).decode()
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    for app in apps:
        repo = data["apps"][app]["repo"]
        target = f"{data['mirrors']['gitlabSources']}/{repo.split('/')[1]}-mirror"
        with tempfile.TemporaryDirectory() as tmp:
            clone = subprocess.run(["git", "clone", "--quiet", "--mirror", f"https://github.com/{repo}.git", tmp],
                                   capture_output=True, text=True, env=env)
            if clone.returncode != 0:
                report.fail(f"cloning {repo} failed (taken down?); GitLab mirror {target} kept as is")
                continue
            try:
                ensure_project(target, repo, token)
            except Exception as err:
                report.fail(f"creating GitLab project {target}: {err}")
                continue
            push = subprocess.run(
                ["git", "-C", tmp, "-c", f"http.extraHeader=Authorization: Basic {auth}", "push", "--porcelain",
                 f"https://gitlab.com/{target}.git", "refs/heads/*:refs/heads/*", "refs/tags/*:refs/tags/*"],
                capture_output=True, text=True, env=env,
            )
            # --porcelain: "<flag>\t<from>:<to>\t<summary>"; '!' rejected, '=' up to date.
            flags = [line[0] for line in push.stdout.splitlines() if "\t" in line]
            if "!" in flags:
                report.fail(f"{target}: upstream rewrote history; mirror kept the old refs")
            elif push.returncode != 0:
                report.fail(f"pushing {target}: {push.stderr[-500:]}")
            elif any(flag != "=" for flag in flags):
                report.info(f"source mirror {target} updated")
