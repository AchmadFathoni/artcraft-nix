"""Track upstream ArtCraft releases: verify, mirror and record them in versions.json.

Run daily by .github/workflows/update.yml. Needs GH_TOKEN (contents: write on
this repo) and GITLAB_TOKEN (scopes api + write_repository). Exits non-zero
when something needs attention (see the report). Only a run that finished
writes `completed=true` to $GITHUB_OUTPUT; a crash restores versions.json and
flake.lock, so the workflow commits nothing half-done.
"""

import argparse
import os
import subprocess
import sys

import common
import mirrors
import sources
import upstream
import verify


def bump_nixpkgs(apps, report):
    """Update flake.lock; keep it only if the newest of every app still builds."""
    lock = common.ROOT / "flake.lock"
    old = lock.read_text()
    subprocess.run(["nix", "flake", "update", "--flake", str(common.ROOT)], check=True)
    if lock.read_text() == old:
        return
    broken = [p for app in apps for p in verify.check(verify.attr(app))]
    if broken:
        lock.write_text(old)
        report.fail("nixpkgs bump kept back, it broke: " + "; ".join(broken))
    else:
        report.info("bumped nixpkgs")


def add_new_versions(data, apps, report):
    """Add, build and check every upstream version the manifest lacks."""
    for app in apps:
        info = data["apps"][app]
        found = upstream.discover(info["repo"])
        if found is None:
            report.fail(f"{app}: upstream {info['repo']} is gone; mirrors keep serving known versions")
            continue
        for version in sorted(set(found) - set(info["versions"]), key=common.vkey):
            info["versions"][version] = found[version]
            common.save(data)  # nix builds from the file on disk
            problems = verify.check(verify.attr(app, version))
            if problems:
                del info["versions"][version]
                common.save(data)
                report.fail(f"{app} {version} not published: " + "; ".join(problems))
            else:
                report.info(f"added {app} {version}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bump-nixpkgs", action="store_true", help="also update flake.lock (weekly)")
    parser.add_argument("--no-mirror", action="store_true", help="discover and verify only")
    parser.add_argument("--only", nargs="+", metavar="APP", help="limit to these apps")
    args = parser.parse_args()

    report, data = common.Report(), common.load()
    apps = args.only or list(data["apps"])
    lock = common.ROOT / "flake.lock"
    originals = {path: path.read_text() for path in (common.MANIFEST, lock)}
    try:
        if args.bump_nixpkgs:
            bump_nixpkgs(apps, report)
        add_new_versions(data, apps, report)
        if not args.no_mirror:
            token = os.environ.get("GITLAB_TOKEN")
            mirrors.ensure(data, apps, token, report)
            sources.mirror(data, apps, token, report)
    except BaseException:
        for path, text in originals.items():
            path.write_text(text)
        raise
    report.write()
    if out := os.environ.get("GITHUB_OUTPUT"):
        changes = [line for line in report.lines if line.startswith(("added", "bumped"))]
        with open(out, "a") as f:
            f.write("completed=true\n")
            f.write(f"message={'; '.join(changes) or 'refresh mirrors'}\n")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
