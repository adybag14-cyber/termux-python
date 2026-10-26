#!/usr/bin/env python3
"""Select a published stable Wrangler release with an available, pinned source."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

REPOSITORY = "https://github.com/cloudflare/workers-sdk.git"
REGISTRY = "https://registry.npmjs.org/wrangler/"
USER_AGENT = "termux-python-builder/1.0 (+https://github.com/adybag14-cyber/termux-python)"


def version_tuple(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
        raise ValueError(f"Not a stable Wrangler version: {value!r}")
    return tuple(map(int, value.split(".")))


def fetch_package(version: str) -> dict | None:
    for attempt in range(4):
        try:
            request = urllib.request.Request(REGISTRY + version, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code != 429 and exc.code < 500:
                raise
            if attempt == 3:
                raise
        except (OSError, urllib.error.URLError):
            if attempt == 3:
                raise
        time.sleep(2 * (attempt + 1))
    raise RuntimeError("Registry retries exhausted")


def parse_source_tags(output: str) -> dict[str, str]:
    direct: dict[str, str] = {}
    peeled: dict[str, str] = {}
    for line in output.splitlines():
        match = re.fullmatch(
            r"([0-9a-f]{40})\s+refs/tags/wrangler@([0-9]+\.[0-9]+\.[0-9]+)(\^\{\})?", line
        )
        if match:
            sha, version, annotation = match.groups()
            entries = peeled if annotation else direct
            if version in entries and entries[version] != sha:
                raise RuntimeError(f"Conflicting source refs for Wrangler {version}")
            entries[version] = sha
    return {version: peeled.get(version, sha) for version, sha in direct.items()}


def select_source(
    latest: str, tags: dict[str, str], package_lookup: Callable[[str], dict | None]
) -> dict[str, str | bool]:
    ceiling = version_tuple(latest)
    candidates = sorted(
        (version for version in tags if version_tuple(version)[0] == ceiling[0]
         and version_tuple(version) <= ceiling),
        key=version_tuple,
        reverse=True,
    )
    # A tag can precede the npm publish, just as npm can precede its source tag.
    # Bound both requests and fallback distance; never fabricate matching source.
    for version in candidates[:10]:
        package = package_lookup(version)
        if package is None:
            continue
        if package.get("name") != "wrangler" or package.get("version") != version:
            raise RuntimeError(f"Registry identity mismatch for Wrangler {version}")
        return {
            "requested_version": latest,
            "version": version,
            "source_tag": f"wrangler@{version}",
            "source_commit": tags[version],
            "fallback": version != latest,
        }
    raise RuntimeError(f"No published stable Wrangler source is available at or below {latest}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", required=True, type=Path)
    args = parser.parse_args()
    latest = fetch_package("latest")
    if latest is None or latest.get("name") != "wrangler":
        raise RuntimeError("Latest Wrangler registry metadata is unavailable")
    output = subprocess.check_output(
        ["git", "ls-remote", "--tags", REPOSITORY, "refs/tags/wrangler@*"],
        text=True,
        timeout=120,
    )
    result = select_source(latest["version"], parse_source_tags(output), fetch_package)
    if result["fallback"]:
        print(
            f"Wrangler {result['requested_version']} has no published matching source; "
            f"building source-backed {result['version']} instead.", file=sys.stderr,
        )
    args.write.parent.mkdir(parents=True, exist_ok=True)
    args.write.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
