#!/usr/bin/env python3
"""Resolve the newest stable CPython patch release for every supported series."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PYTHON_FTP = "https://www.python.org/ftp/python/"
TERMUX_PYTHON_RECIPE = (
    "https://raw.githubusercontent.com/termux/termux-packages/master/packages/python/build.sh"
)
USER_AGENT = "termux-python-builder/1.0 (+https://github.com/adybag14-cyber/termux-python)"


def fetch_text(url: str, attempts: int = 4) -> str:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read().decode("utf-8", errors="replace")
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt != attempts:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to fetch {url}: {last_error}")


def stable_python_versions() -> dict[str, str]:
    html = fetch_text(PYTHON_FTP)
    found: dict[str, tuple[int, int, int]] = {}
    for major, minor, patch in re.findall(r'href=["\'](\d+)\.(\d+)\.(\d+)/["\']', html):
        version_tuple = (int(major), int(minor), int(patch))
        if version_tuple[0] != 3 or version_tuple[1] < 9:
            continue
        key = f"{version_tuple[0]}.{version_tuple[1]}"
        if version_tuple > found.get(key, (0, 0, 0)):
            found[key] = version_tuple
    if not found:
        raise RuntimeError("No stable CPython versions were found in the Python.org FTP index")
    return {key: ".".join(map(str, value)) for key, value in sorted(found.items())}


def current_termux_python() -> tuple[str, str] | None:
    recipe = fetch_text(TERMUX_PYTHON_RECIPE)
    match = re.search(r'^TERMUX_PKG_VERSION=["\']?(\d+\.\d+\.\d+)["\']?\s*$', recipe, re.M)
    if not match:
        return None
    version = match.group(1)
    return ".".join(version.split(".")[:2]), version


def parse_requested(value: str) -> set[str] | None:
    if value.strip().lower() in {"", "all", "*"}:
        return None
    requested = {item.strip() for item in value.split(",") if item.strip()}
    invalid = [item for item in requested if not re.fullmatch(r"3\.\d+", item)]
    if invalid:
        raise ValueError(f"Invalid Python series: {', '.join(sorted(invalid))}")
    return requested


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/series.json")
    parser.add_argument("--series", default=os.environ.get("PYTHON_SERIES", "all"))
    parser.add_argument("--write", help="Write the resolved metadata to this JSON file")
    parser.add_argument(
        "--github-output",
        default=os.environ.get("GITHUB_OUTPUT"),
        help="Append matrix and count outputs to a GitHub Actions output file",
    )
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    available = stable_python_versions()
    requested = parse_requested(args.series)

    configured: dict[str, dict[str, object]] = {
        str(item["minor"]): dict(item) for item in config["series"]
    }

    # Future Python series are picked up automatically once Termux's own master
    # recipe supports them. This avoids trying to apply a 3.14 patch set to 3.15.
    termux_current = current_termux_python()
    if termux_current:
        termux_minor, termux_version = termux_current
        if termux_minor not in configured and termux_minor in available:
            configured[termux_minor] = {
                "minor": termux_minor,
                "recipe_ref": "master",
                "recipe_baseline": termux_version,
                "support": "auto-discovered",
            }

    matrix: list[dict[str, object]] = []
    for minor in sorted(configured, key=lambda value: tuple(map(int, value.split(".")))):
        if requested is not None and minor not in requested:
            continue
        if minor not in available:
            print(f"warning: Python {minor} has no stable source release in the FTP index", file=sys.stderr)
            continue
        item = configured[minor]
        matrix.append(
            {
                "minor": minor,
                "version": available[minor],
                "recipe_ref": item["recipe_ref"],
                "recipe_baseline": item["recipe_baseline"],
                "support": item.get("support", "unknown"),
                "arch": config.get("architecture", "aarch64"),
                "api": int(config.get("minimum_android_api", 24)),
            }
        )

    if requested is not None:
        unresolved = requested - {str(item["minor"]) for item in matrix}
        if unresolved:
            raise RuntimeError(f"Requested series could not be resolved: {', '.join(sorted(unresolved))}")

    payload = {
        "generated_at_epoch": int(time.time()),
        "python_ftp": PYTHON_FTP,
        "termux_recipe": TERMUX_PYTHON_RECIPE,
        "include": matrix,
    }
    compact_matrix = json.dumps({"include": matrix}, separators=(",", ":"))
    print(json.dumps(payload, indent=2))

    if args.write:
        Path(args.write).parent.mkdir(parents=True, exist_ok=True)
        Path(args.write).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"matrix={compact_matrix}\n")
            handle.write(f"count={len(matrix)}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
