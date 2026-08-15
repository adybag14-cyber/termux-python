#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

RELEASE_SOURCES = {
    # Scan recent releases so targeted immutable hotfix releases can coexist with
    # the complete weekly bundle without taking over GitHub's Latest pointer.
    "adybag14-cyber/termux-python": 20,
    # Hermes package releases are deliberately not marked "Latest" because
    # termux-hermes also publishes the canonical dependency wheelhouse there.
    "adybag14-cyber/termux-hermes": 20,
}
INCOMING = Path("/srv/termux-repo/incoming")
CURRENT_POOL = Path("/srv/termux-repo/current/termux/pool/main")
USER_AGENT = "adybag-termux-repo-sync/1.1"
ALLOWED = (
    re.compile(r"python3\.\d+(?:-ensurepip-wheels)?_[^/]+_(?:aarch64|all)\.deb$"),
    re.compile(r"uv_[^/]+_aarch64\.deb$"),
    re.compile(r"wrangler_[^/]+_aarch64\.deb$"),
    re.compile(r"hermes-agent_[^/]+_aarch64\.deb$"),
)


def api_json(url: str):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.load(response)


def releases(repo: str, limit: int) -> list[dict]:
    if limit == 1:
        item = api_json(f"https://api.github.com/repos/{repo}/releases/latest")
        return [item]
    items = api_json(f"https://api.github.com/repos/{repo}/releases?per_page={limit}")
    return [item for item in items if not item.get("draft") and not item.get("prerelease")]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def allowed(name: str) -> bool:
    return any(pattern.fullmatch(name) for pattern in ALLOWED)


def parse_deb_filename(name: str) -> tuple[str, str, str]:
    if not name.endswith(".deb"):
        raise ValueError(f"Not a Debian package filename: {name}")
    try:
        package, version, arch = name[:-4].rsplit("_", 2)
    except ValueError as exc:
        raise ValueError(f"Malformed Debian package filename: {name}") from exc
    if not package or not version or not arch:
        raise ValueError(f"Malformed Debian package filename: {name}")
    return package, version, arch


def deb_metadata(path: Path) -> tuple[str, str, str]:
    # dpkg-deb prints ``Field: value`` labels when multiple fields are requested
    # together, but prints only the value for a single requested field. Query
    # separately so the result is stable across dpkg versions.
    def field(name: str) -> str:
        return subprocess.check_output(
            ["dpkg-deb", "-f", str(path), name], text=True
        ).strip()

    return field("Package"), field("Version"), field("Architecture")


def metadata_ok(path: Path, expected: tuple[str, str, str]) -> bool:
    package, version, arch = deb_metadata(path)
    if (package, version, arch) != expected:
        return False
    if package == "python":
        return False
    if not (
        re.fullmatch(r"python3\.\d+(?:-ensurepip-wheels)?", package)
        or package in {"uv", "wrangler", "hermes-agent"}
    ):
        return False
    return arch in {"aarch64", "all"}


def version_gt(candidate: str, current: str) -> bool:
    return subprocess.run(
        ["dpkg", "--compare-versions", candidate, "gt", current],
        check=False,
    ).returncode == 0


def current_versions() -> dict[tuple[str, str], str]:
    versions: dict[tuple[str, str], str] = {}
    if not CURRENT_POOL.is_dir():
        return versions
    for deb in CURRENT_POOL.glob("*.deb"):
        package, version, arch = deb_metadata(deb)
        key = (package, arch)
        previous = versions.get(key)
        if previous is None or version_gt(version, previous):
            versions[key] = version
    return versions


def main() -> int:
    INCOMING.mkdir(parents=True, exist_ok=True)
    live_versions = current_versions()
    changed = False
    for repo, limit in RELEASE_SOURCES.items():
        seen_names: set[str] = set()
        repo_releases = releases(repo, limit)
        print(f"{repo}: inspecting {len(repo_releases)} release(s)")
        for release in repo_releases:
            tag = release.get("tag_name")
            for asset in release.get("assets", []):
                name = asset.get("name", "")
                if name in seen_names or not allowed(name):
                    continue
                seen_names.add(name)
                identity = parse_deb_filename(name)
                package, version, arch = identity
                live_version = live_versions.get((package, arch))
                if live_version is not None and not version_gt(version, live_version):
                    print(
                        f"  skip {tag}/{name}: version {version} is not newer than "
                        f"active {package} {live_version}"
                    )
                    continue
                digest = asset.get("digest") or ""
                expected = digest.split(":", 1)[1] if digest.startswith("sha256:") else None
                if not expected:
                    print(f"  skip {tag}/{name}: GitHub SHA-256 digest missing")
                    continue
                current = CURRENT_POOL / name
                if current.is_file():
                    current_digest = sha256(current)
                    if current_digest == expected:
                        continue
                    # APT identifies upgrades by package Version, not release tag.
                    # Never replace an already-published package filename/version
                    # with different bytes; producers must bump the package version.
                    print(
                        f"  skip {tag}/{name}: active package already exists with "
                        f"different digest {current_digest}; bump the package version"
                    )
                    continue
                url = asset.get("browser_download_url")
                if not url:
                    continue
                fd, temp_name = tempfile.mkstemp(
                    prefix=name + ".", suffix=".partial", dir=str(INCOMING)
                )
                os.close(fd)
                temp = Path(temp_name)
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                    with urllib.request.urlopen(req, timeout=180) as response, temp.open("wb") as out:
                        for chunk in iter(lambda: response.read(1024 * 1024), b""):
                            out.write(chunk)
                    actual = sha256(temp)
                    if actual != expected:
                        raise RuntimeError(
                            f"SHA-256 mismatch for {repo}/{tag}/{name}: {actual} != {expected}"
                        )
                    if not metadata_ok(temp, identity):
                        raise RuntimeError(
                            f"Rejected package metadata/filename mismatch for {repo}/{tag}/{name}"
                        )
                    os.replace(temp, INCOMING / name)
                    live_versions[(package, arch)] = version
                    print(f"  staged {tag}/{name} sha256={actual}")
                    changed = True
                finally:
                    temp.unlink(missing_ok=True)
    if changed:
        print("New verified APT packages staged; systemd publisher will sign and publish them")
    else:
        print("No new APT packages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())