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
    "adybag14-cyber/termux-python": 1,
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


def metadata_ok(path: Path) -> bool:
    package = subprocess.check_output(
        ["dpkg-deb", "-f", str(path), "Package"], text=True
    ).strip()
    arch = subprocess.check_output(
        ["dpkg-deb", "-f", str(path), "Architecture"], text=True
    ).strip()
    if package == "python":
        return False
    if not (
        re.fullmatch(r"python3\.\d+(?:-ensurepip-wheels)?", package)
        or package in {"uv", "wrangler", "hermes-agent"}
    ):
        return False
    return arch in {"aarch64", "all"}


def main() -> int:
    INCOMING.mkdir(parents=True, exist_ok=True)
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
                digest = asset.get("digest") or ""
                expected = digest.split(":", 1)[1] if digest.startswith("sha256:") else None
                if not expected:
                    print(f"  skip {tag}/{name}: GitHub SHA-256 digest missing")
                    continue
                current = CURRENT_POOL / name
                if current.is_file() and sha256(current) == expected:
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
                    if not metadata_ok(temp):
                        raise RuntimeError(f"Rejected package metadata for {repo}/{tag}/{name}")
                    os.replace(temp, INCOMING / name)
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