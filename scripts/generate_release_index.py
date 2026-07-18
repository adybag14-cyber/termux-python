#!/usr/bin/env python3
"""Create machine-readable release indexes and SHA-256 checksums."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wheel_minor(filename: str) -> str | None:
    match = re.search(r"-cp(3\d{1,2})-cp\1-", filename)
    if not match:
        return None
    digits = match.group(1)
    return f"{digits[0]}.{digits[1:]}"


def classify(path: Path) -> tuple[str, str, str] | None:
    name = path.name
    match = re.fullmatch(r"python_((\d+)\.(\d+)\.\d+[^_]*)_aarch64\.deb", name)
    if match:
        return "python", f"{match.group(2)}.{match.group(3)}", match.group(1)

    match = re.fullmatch(
        r"python-ensurepip-wheels_((\d+)\.(\d+)\.\d+[^_]*)_(?:all|aarch64)\.deb",
        name,
    )
    if match:
        return "ensurepip", f"{match.group(2)}.{match.group(3)}", match.group(1)

    match = re.fullmatch(r"uv_([^_]+)_aarch64\.deb", name)
    if match:
        return "uv", "-", match.group(1)

    if name.startswith("psutil-") and name.endswith(".whl"):
        minor = wheel_minor(name)
        version_match = re.match(r"psutil-([^-]+)-", name)
        if minor and version_match:
            return "psutil", minor, version_match.group(1)

    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, str | int]] = []

    for path in sorted(args.assets.rglob("*")):
        if not path.is_file() or path.name in {
            "release-index.json",
            "release-index.tsv",
            "SHA256SUMS",
        }:
            continue
        classified = classify(path)
        if not classified:
            continue
        kind, minor, version = classified
        checksum = sha256(path)
        records.append(
            {
                "kind": kind,
                "minor": minor,
                "version": version,
                "architecture": "aarch64",
                "filename": path.name,
                "size": path.stat().st_size,
                "sha256": checksum,
                "url": (
                    f"https://github.com/{args.repo}/releases/download/"
                    f"{quote(args.tag, safe='')}/{quote(path.name, safe='')}"
                ),
            }
        )

    if not records:
        raise RuntimeError(f"No publishable assets were found below {args.assets}")

    payload = {
        "schema": 1,
        "repository": args.repo,
        "release_tag": args.tag,
        "architecture": "aarch64",
        "assets": records,
    }
    (args.output / "release-index.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    with (args.output / "release-index.tsv").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("kind\tminor\tversion\tarchitecture\tfilename\tsha256\turl\n")
        for item in records:
            handle.write(
                "\t".join(
                    str(item[key])
                    for key in (
                        "kind",
                        "minor",
                        "version",
                        "architecture",
                        "filename",
                        "sha256",
                        "url",
                    )
                )
                + "\n"
            )

    with (args.output / "SHA256SUMS").open("w", encoding="utf-8", newline="\n") as handle:
        for item in records:
            handle.write(f"{item['sha256']}  {item['filename']}\n")

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
