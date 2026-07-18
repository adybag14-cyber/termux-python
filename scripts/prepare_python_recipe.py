#!/usr/bin/env python3
"""Install a version-matched historical Termux Python recipe into a current tree."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "termux-python-builder/1.0 (+https://github.com/adybag14-cyber/termux-python)"


def run(*args: str, cwd: Path | None = None) -> bytes:
    return subprocess.check_output(args, cwd=cwd)


def fetch_bytes(url: str, attempts: int = 4) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt != attempts:
                time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to download {url}: {last_error}")


def extract_recipe(tree: Path, recipe_ref: str) -> None:
    archive = run("git", "archive", "--format=tar", recipe_ref, "packages/python", cwd=tree)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            tar.extractall(tmp, filter="data")
        source = tmp / "packages" / "python"
        if not source.is_dir():
            raise RuntimeError(f"Recipe packages/python was not present at {recipe_ref}")
        destination = tree / "packages" / "python"
        shutil.rmtree(destination, ignore_errors=True)
        shutil.copytree(source, destination)


def replace_version(build_sh: str, version: str) -> str:
    updated, count = re.subn(
        r"^TERMUX_PKG_VERSION=.*$",
        f'TERMUX_PKG_VERSION="{version}"',
        build_sh,
        count=1,
        flags=re.M,
    )
    if count != 1:
        raise RuntimeError("Could not replace TERMUX_PKG_VERSION in the selected recipe")
    return updated


def replace_source_checksum(build_sh: str, checksum: str) -> str:
    # Newer recipes use an array because they also download Debian helper files.
    array_pattern = re.compile(r"(TERMUX_PKG_SHA256=\(\s*\n\s*)([0-9a-fA-F]{64})")
    updated, count = array_pattern.subn(rf"\g<1>{checksum}", build_sh, count=1)
    if count == 1:
        return updated

    scalar_pattern = re.compile(r"^TERMUX_PKG_SHA256=.*$", re.M)
    updated, count = scalar_pattern.subn(f"TERMUX_PKG_SHA256={checksum}", build_sh, count=1)
    if count != 1:
        raise RuntimeError("Could not replace TERMUX_PKG_SHA256 in the selected recipe")
    return updated


def modernize_recipe(build_sh: str, minor: str) -> str:
    build_sh = build_sh.replace("TERMUX_MAKE_PROCESSES", "TERMUX_PKG_MAKE_PROCESSES")
    build_sh = build_sh.replace(
        'TERMUX_PKG_LICENSE="PythonPL"',
        'TERMUX_PKG_LICENSE="custom"\nTERMUX_PKG_LICENSE_FILE="LICENSE"',
    )

    # Do not allow apt to pull the repository's current python-pip package next
    # to a historical Python ABI. Pip is initialized by our postinst using the
    # matching bundled ensurepip wheels.
    build_sh = re.sub(
        r'^TERMUX_PKG_RECOMMENDS="python-ensurepip-wheels, python-pip"\s*$',
        '# matching ensurepip wheels are installed from the same immutable release',
        build_sh,
        flags=re.M,
    )

    overrides = f"""

# ---- termux-python project overrides ---------------------------------------
# Generated from the version-matched upstream Termux recipe. The package keeps
# the normal name `python`, so installing it intentionally switches the active
# Termux Python version instead of pretending incompatible ABIs can coexist.
TERMUX_PKG_AUTO_UPDATE=false
TERMUX_PKG_DESCRIPTION="CPython {minor} for Termux/Android aarch64"

# Configure pip only after the target package is installed on native Android.
# Newer recipes move Lib/ensurepip/_bundled into python-ensurepip-wheels; apt
# unpacks that matching release asset before it runs this postinst.
termux_step_create_debscripts() {{
    cat <<- POSTINST_EOF > ./postinst
    #!$TERMUX_PREFIX/bin/sh

    rm -Rf $TERMUX_PREFIX/lib/python{minor}/site-packages/pip-*.dist-info
    if ! $TERMUX_PREFIX/bin/python{minor} -m ensurepip --upgrade --default-pip; then
        echo "WARNING: pip bootstrap failed for Python {minor}." >&2
        echo "Install the matching python-ensurepip-wheels asset, then run:" >&2
        echo "  python{minor} -m ensurepip --upgrade --default-pip" >&2
    fi
    exit 0
    POSTINST_EOF
    chmod 0755 ./postinst
}}
# ---------------------------------------------------------------------------
"""
    return build_sh.rstrip() + overrides


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", required=True, type=Path)
    parser.add_argument("--minor", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--recipe-ref", required=True)
    parser.add_argument("--metadata", type=Path)
    args = parser.parse_args()

    expected_minor = ".".join(args.version.split(".")[:2])
    if expected_minor != args.minor:
        raise ValueError(f"Version {args.version} does not belong to series {args.minor}")
    if not (args.tree / ".git").exists():
        raise RuntimeError(f"{args.tree} is not a git checkout")

    extract_recipe(args.tree, args.recipe_ref)

    source_url = f"https://www.python.org/ftp/python/{args.version}/Python-{args.version}.tar.xz"
    source = fetch_bytes(source_url)
    checksum = hashlib.sha256(source).hexdigest()

    recipe_path = args.tree / "packages" / "python" / "build.sh"
    build_sh = recipe_path.read_text(encoding="utf-8")
    build_sh = replace_version(build_sh, args.version)
    build_sh = replace_source_checksum(build_sh, checksum)
    build_sh = modernize_recipe(build_sh, args.minor)
    recipe_path.write_text(build_sh, encoding="utf-8", newline="\n")

    metadata = {
        "minor": args.minor,
        "version": args.version,
        "recipe_ref": args.recipe_ref,
        "source_url": source_url,
        "source_sha256": checksum,
        "source_size": len(source),
    }
    output = args.metadata or (args.tree / "python-build-metadata.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
