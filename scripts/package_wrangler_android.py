#!/usr/bin/env python3
"""Assemble a self-contained Wrangler package for native Termux aarch64."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

TERMUX_STAGING_PREFIX = Path("data/data/com.termux/files/usr")
WORKERD_ANCHOR = "function generateBinPath() {\n  const { pkg, subpath } = pkgAndSubpathForCurrentPlatform();"
WORKERD_ANDROID = """function generateBinPath() {
  // termux-python: upstream workerd does not register Android in its npm
  // platform table. The package launcher points this at the exact Android
  // workerd binary built from source alongside Wrangler.
  if (process.platform === "android" && process.arch === "arm64" && process.env.WORKERD_BINARY_PATH) {
    return { binPath: process.env.WORKERD_BINARY_PATH };
  }
  const { pkg, subpath } = pkgAndSubpathForCurrentPlatform();"""


def executable_copy(source: Path, destination: Path) -> None:
    source = source.resolve(strict=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    destination.chmod(0o755)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_wrangler_self_link(root: Path) -> None:
    link = root / "node_modules" / ".pnpm" / "node_modules" / "wrangler"
    if not link.is_symlink():
        return
    target = link.resolve(strict=True)
    if target == root.resolve():
        return
    package_json = target / "package.json"
    try:
        package = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unexpected external Wrangler self-link target: {target}") from exc
    if package.get("name") != "wrangler":
        raise RuntimeError(f"Unexpected external Wrangler self-link target: {target}")
    link.unlink()
    # From node_modules/.pnpm/node_modules back to the deployment root.
    os.symlink("../../..", link, target_is_directory=True)


TERMUX_RUNTIME_PREFIX = Path("/data/data/com.termux/files/usr")
TERMUX_WRANGLER_HOME = TERMUX_RUNTIME_PREFIX / "lib" / "wrangler"


def deployment_root_variants(root: Path) -> set[str]:
    resolved = str(root.resolve())
    variants = {resolved, resolved.replace("\\", "/")}
    match = re.match(r"^/mnt/([A-Za-z])/(.*)$", resolved)
    if match:
        drive, rest = match.groups()
        windows = drive.upper() + ":\\" + rest.replace("/", "\\")
        variants.update({windows, windows.replace("\\", "/")})
    return {value for value in variants if value}


def normalize_pnpm_bin_shims(root: Path) -> None:
    """Remove Windows shims and rewrite pnpm's absolute deploy-root NODE_PATHs."""
    replacements = deployment_root_variants(root)
    destination = str(TERMUX_WRANGLER_HOME)
    for bin_dir in root.rglob(".bin"):
        if not bin_dir.is_dir():
            continue
        for shim in bin_dir.iterdir():
            if shim.is_symlink() or not shim.is_file():
                continue
            if shim.suffix.lower() in {".cmd", ".ps1"}:
                shim.unlink()
                continue
            try:
                text = shim.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            updated = text
            for source in sorted(replacements, key=len, reverse=True):
                updated = updated.replace(source, destination)
            if any(source in updated for source in replacements):
                raise RuntimeError(f"pnpm shim still contains its staging deployment path: {shim}")
            if updated != text:
                shim.write_text(updated, encoding="utf-8", newline="\n")


def normalize_termux_shebangs(root: Path) -> None:
    """Rewrite conventional Linux shebangs to paths that exist in Termux."""
    replacements = {
        b"#!/bin/sh": b"#!/data/data/com.termux/files/usr/bin/sh",
        b"#!/usr/bin/env sh": b"#!/data/data/com.termux/files/usr/bin/sh",
        b"#!/usr/bin/env node": b"#!/data/data/com.termux/files/usr/bin/node",
        b"#! /usr/bin/env node": b"#!/data/data/com.termux/files/usr/bin/node",
        b"#!/usr/bin/env bash": b"#!/data/data/com.termux/files/usr/bin/bash",
    }
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        newline = data.find(b"\n")
        if newline < 0:
            continue
        first_line = data[:newline].rstrip(b"\r")
        replacement = replacements.get(first_line)
        if replacement is not None:
            path.write_bytes(replacement + b"\n" + data[newline + 1 :])


def remove_foreign_native_payloads(root: Path) -> None:
    """Drop foreign PE/Mach-O helpers and reject accidental host ELF payloads."""
    macho_magics = {
        b"\xfe\xed\xfa\xce",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
    }
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            with path.open("rb") as handle:
                magic = handle.read(4)
        except OSError:
            continue
        if magic.startswith(b"MZ") or magic in macho_magics:
            print(f"Removing foreign native payload: {path.relative_to(root)}")
            path.unlink()
            continue
        if magic.startswith(b"\x7fELF"):
            raise RuntimeError(f"Deployment contains an unexpected host ELF binary: {path}")


def verify_self_contained(root: Path) -> None:
    resolved_root = root.resolve()
    for path in root.rglob("*"):
        if not path.is_symlink():
            continue
        try:
            target = path.resolve(strict=True)
            target.relative_to(resolved_root)
        except (FileNotFoundError, ValueError) as exc:
            raise RuntimeError(f"Deployment contains an external or broken symlink: {path}") from exc

        # pnpm uses relative symlinks on Linux, but a deployment produced on
        # Windows may expose equivalent directory junctions as absolute links
        # through WSL. They are self-contained before relocation but would point
        # back to the original staging tree after copytree(..., symlinks=True).
        # Canonicalize every validated internal link to a relative target first.
        relative_target = os.path.relpath(target, start=path.parent)
        raw_target = os.readlink(path)
        if raw_target != relative_target:
            target_is_directory = target.is_dir()
            path.unlink()
            os.symlink(relative_target, path, target_is_directory=target_is_directory)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deploy", required=True, type=Path)
    parser.add_argument("--workerd-binary", required=True, type=Path)
    parser.add_argument("--esbuild-binary", required=True, type=Path)
    parser.add_argument("--wrangler-version", required=True)
    parser.add_argument("--workerd-version", required=True)
    parser.add_argument("--esbuild-version", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    deploy = args.deploy.resolve(strict=True)
    normalize_wrangler_self_link(deploy)
    normalize_pnpm_bin_shims(deploy)
    normalize_termux_shebangs(deploy)
    remove_foreign_native_payloads(deploy)
    verify_self_contained(deploy)
    package_json = deploy / "package.json"
    package = json.loads(package_json.read_text(encoding="utf-8"))
    if package.get("name") != "wrangler" or package.get("version") != args.wrangler_version:
        raise RuntimeError(
            f"Unexpected deployment identity: {package.get('name')}@{package.get('version')}"
        )
    if not (deploy / "bin" / "wrangler.js").is_file():
        raise RuntimeError("Wrangler deployment is missing bin/wrangler.js")

    forbidden_native = (
        "@cloudflare/workerd-linux",
        "@cloudflare/workerd-windows",
        "@cloudflare/workerd-darwin",
        "@esbuild/linux",
        "@esbuild/win32",
        "@esbuild/darwin",
        "@img/sharp-linux",
        "@img/sharp-win32",
        "@img/sharp-darwin",
        "@img/sharp-wasm",
        "@img/sharp-libvips-linux",
        "@img/sharp-libvips-darwin",
        "@img/sharp-libvips-wasm",
    )
    for path in deploy.rglob("package.json"):
        try:
            name = json.loads(path.read_text(encoding="utf-8")).get("name", "")
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if any(name.startswith(prefix) for prefix in forbidden_native):
            raise RuntimeError(f"Host-native dependency leaked into Wrangler deployment: {name}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"wrangler_{args.wrangler_version}_aarch64.deb"

    with tempfile.TemporaryDirectory(prefix="wrangler-termux-") as temp:
        package_root = Path(temp)
        prefix = package_root / TERMUX_STAGING_PREFIX
        app = prefix / "lib" / "wrangler"
        shutil.copytree(deploy, app, symlinks=True)

        workerd_main = (app / "node_modules" / "workerd" / "lib" / "main.js").resolve(strict=True)
        try:
            workerd_main.relative_to(app.resolve())
        except ValueError as exc:
            raise RuntimeError("workerd runtime resolved outside Wrangler deployment") from exc
        workerd_text = workerd_main.read_text(encoding="utf-8")
        if WORKERD_ANCHOR not in workerd_text:
            raise RuntimeError("Unexpected workerd runtime layout; Android patch anchor missing")
        workerd_main.write_text(
            workerd_text.replace(WORKERD_ANCHOR, WORKERD_ANDROID, 1), encoding="utf-8"
        )

        native = app / "native"
        workerd_path = native / "workerd"
        esbuild_path = native / "esbuild"
        executable_copy(args.workerd_binary, workerd_path)
        executable_copy(args.esbuild_binary, esbuild_path)
        workerd_sha256 = sha256_file(workerd_path)
        esbuild_sha256 = sha256_file(esbuild_path)

        bin_dir = prefix / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        launcher = bin_dir / "wrangler"
        launcher.write_text(
            """#!/data/data/com.termux/files/usr/bin/sh
set -eu
PREFIX=${PREFIX:-/data/data/com.termux/files/usr}
export WRANGLER_HOME="$PREFIX/lib/wrangler"
export WORKERD_BINARY_PATH="$WRANGLER_HOME/native/workerd"
export MINIFLARE_WORKERD_PATH="$WORKERD_BINARY_PATH"
export ESBUILD_BINARY_PATH="$WRANGLER_HOME/native/esbuild"
exec "$PREFIX/bin/node" "$WRANGLER_HOME/bin/wrangler.js" "$@"
""",
            encoding="utf-8",
            newline="\n",
        )
        launcher.chmod(0o755)
        for alias in ("wrangler2", "cf-wrangler"):
            os.symlink("wrangler", bin_dir / alias)

        docs = prefix / "share" / "doc" / "wrangler"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "BUILD-METADATA.txt").write_text(
            f"""Wrangler: {args.wrangler_version}
workerd: {args.workerd_version}
workerd SHA-256: {workerd_sha256}
esbuild: {args.esbuild_version}
esbuild SHA-256: {esbuild_sha256}
target: aarch64-linux-android
minimum Android API: 24
Wrangler source: https://github.com/cloudflare/workers-sdk
workerd source: https://github.com/cloudflare/workerd
esbuild source: https://github.com/evanw/esbuild
""",
            encoding="utf-8",
            newline="\n",
        )

        debian = package_root / "DEBIAN"
        debian.mkdir()
        (debian / "control").write_text(
            f"""Package: wrangler
Version: {args.wrangler_version}
Architecture: aarch64
Maintainer: adybag14-cyber
Depends: nodejs (>= 22) | nodejs-lts (>= 22), libc++
Section: devel
Priority: optional
Homepage: https://github.com/cloudflare/workers-sdk
Description: Cloudflare Wrangler CLI built from source for Termux aarch64
 Includes Wrangler from the matching workers-sdk release together with
 Android/Bionic aarch64 builds of its matching workerd and esbuild versions.
""",
            encoding="utf-8",
            newline="\n",
        )

        subprocess.run(
            ["dpkg-deb", "--build", "--root-owner-group", str(package_root), str(output)],
            check=True,
        )

    subprocess.run(["dpkg-deb", "--info", str(output)], check=True)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())