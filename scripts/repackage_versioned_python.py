#!/usr/bin/env python3
"""Repackage a tested Termux CPython .deb for safe side-by-side APT installs.

The upstream Termux recipe intentionally owns generic aliases such as `python`,
`python3`, generic pkg-config files and libpython3.so.  Those files are correct
for Termux's rolling `python` package but would make historical interpreters
collide with each other and with the official repository.  This tool preserves
only version-qualified payloads and emits package names such as `python3.13`.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

PREFIX = Path("data/data/com.termux/files/usr")
GENERIC_PATHS = (
    "bin/2to3",
    "bin/idle",
    "bin/idle3",
    "bin/pip",
    "bin/pip3",
    "bin/py3clean",
    "bin/py3compile",
    "bin/pydoc",
    "bin/pydoc3",
    "bin/python",
    "bin/python-config",
    "bin/python3",
    "bin/python3-config",
    "lib/libpython3.so",
    "lib/pkgconfig/python3-embed.pc",
    "lib/pkgconfig/python3.pc",
    "share/doc/python/LICENSE",
    "share/man/man1/python.1.gz",
    "share/man/man1/python3.1.gz",
)
DROP_CONTROL_FIELDS = {"Breaks", "Conflicts", "Provides", "Recommends", "Replaces", "Suggests"}


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def deb_field(deb: Path, field: str) -> str:
    return subprocess.check_output(["dpkg-deb", "-f", str(deb), field], text=True).strip()


def minor_from_version(version: str) -> str:
    match = re.match(r"^(\d+)\.(\d+)(?:\.|$)", version)
    if not match:
        raise ValueError(f"Cannot derive Python minor from version {version!r}")
    return f"{match.group(1)}.{match.group(2)}"


def rewrite_control(control: Path, *, package: str, version: str, ensure_package: str | None) -> None:
    lines = control.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    saw_package = saw_depends = saw_description = False
    for line in lines:
        if not line or line[0].isspace() or ":" not in line:
            out.append(line)
            continue
        field, value = line.split(":", 1)
        if field in DROP_CONTROL_FIELDS:
            continue
        if field == "Package":
            out.append(f"Package: {package}")
            saw_package = True
        elif field == "Maintainer":
            out.append("Maintainer: adybag14-cyber <adybag14-cyber@users.noreply.github.com>")
        elif field == "Depends":
            deps = value.strip()
            if ensure_package:
                deps = f"{deps}, {ensure_package} (= {version})" if deps else f"{ensure_package} (= {version})"
            out.append(f"Depends: {deps}")
            saw_depends = True
        elif field == "Description":
            out.append(f"Description: CPython {minor_from_version(version)} side-by-side runtime for Termux aarch64")
            saw_description = True
        else:
            out.append(line)
    if not saw_package:
        raise RuntimeError(f"Missing Package field in {control}")
    if ensure_package and not saw_depends:
        out.append(f"Depends: {ensure_package} (= {version})")
    if not saw_description:
        out.append(f"Description: CPython {minor_from_version(version)} side-by-side runtime for Termux aarch64")
    control.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def repackage_ensurepip(source: Path, output_dir: Path, *, minor: str, version: str) -> Path:
    expected = "python-ensurepip-wheels"
    if deb_field(source, "Package") != expected:
        raise RuntimeError(f"Expected {expected}, got {deb_field(source, 'Package')}")
    package = f"python{minor}-ensurepip-wheels"
    with tempfile.TemporaryDirectory(prefix="termux-ensurepip-") as td:
        root = Path(td) / "root"
        run("dpkg-deb", "-R", str(source), str(root))
        control = root / "DEBIAN" / "control"
        lines = control.read_text(encoding="utf-8").splitlines()
        out: list[str] = []
        for line in lines:
            if line.startswith("Package:"):
                out.append(f"Package: {package}")
            elif line.startswith("Maintainer:"):
                out.append("Maintainer: adybag14-cyber <adybag14-cyber@users.noreply.github.com>")
            elif any(line.startswith(f"{field}:") for field in ("Depends", "Breaks", "Conflicts", "Provides", "Replaces")):
                continue
            elif line.startswith("Description:"):
                out.append(f"Description: ensurepip wheels for side-by-side CPython {minor} on Termux")
            else:
                out.append(line)
        control.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
        output = output_dir / f"{package}_{version}_all.deb"
        run("dpkg-deb", "--build", "--root-owner-group", str(root), str(output))
    return output


def write_maintainer_scripts(root: Path, *, minor: str, has_ensurepip: bool) -> None:
    debian = root / "DEBIAN"
    postinst = debian / "postinst"
    prerm = debian / "prerm"
    python = f"/data/data/com.termux/files/usr/bin/python{minor}"
    pip = f"/data/data/com.termux/files/usr/bin/pip{minor}"
    site = f"/data/data/com.termux/files/usr/lib/python{minor}/site-packages"
    if has_ensurepip:
        postinst.write_text(
            "#!/data/data/com.termux/files/usr/bin/sh\n"
            "set -eu\n"
            "if [ \"${1:-}\" = configure ]; then\n"
            f"  rm -Rf '{site}'/pip-*.dist-info\n"
            f"  if ! '{python}' -m ensurepip --upgrade --altinstall; then\n"
            f"    echo 'WARNING: pip bootstrap failed for Python {minor}; run: python{minor} -m ensurepip --upgrade --altinstall' >&2\n"
            "  fi\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
    else:
        postinst.write_text("#!/data/data/com.termux/files/usr/bin/sh\nexit 0\n", encoding="utf-8")
    prerm.write_text(
        "#!/data/data/com.termux/files/usr/bin/sh\n"
        "set -eu\n"
        "if [ \"${1:-}\" = remove ]; then\n"
        f"  rm -f '{pip}'\n"
        f"  rm -Rf '{site}'/pip '{site}'/pip-*.dist-info\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    postinst.chmod(0o755)
    prerm.chmod(0o755)


def repackage_python(source: Path, output_dir: Path, *, ensurepip: Path | None = None) -> tuple[Path, Path | None]:
    if deb_field(source, "Package") != "python":
        raise RuntimeError(f"Expected Package: python, got {deb_field(source, 'Package')}")
    version = deb_field(source, "Version")
    arch = deb_field(source, "Architecture")
    if arch != "aarch64":
        raise RuntimeError(f"Only aarch64 is supported, got {arch}")
    minor = minor_from_version(version)
    package = f"python{minor}"
    output_dir.mkdir(parents=True, exist_ok=True)

    ensure_output: Path | None = None
    ensure_name: str | None = None
    if ensurepip is not None:
        if deb_field(ensurepip, "Version") != version:
            raise RuntimeError("Python and ensurepip package versions do not match")
        ensure_output = repackage_ensurepip(ensurepip, output_dir, minor=minor, version=version)
        ensure_name = f"python{minor}-ensurepip-wheels"

    with tempfile.TemporaryDirectory(prefix="termux-python-versioned-") as td:
        root = Path(td) / "root"
        run("dpkg-deb", "-R", str(source), str(root))
        for relative in GENERIC_PATHS:
            path = root / PREFIX / relative
            if path.is_symlink() or path.is_file():
                path.unlink()
        # Remove now-empty generic doc directory if possible.
        doc = root / PREFIX / "share/doc/python"
        if doc.is_dir():
            shutil.rmtree(doc)
        rewrite_control(root / "DEBIAN" / "control", package=package, version=version, ensure_package=ensure_name)
        bundled_wheels = root / PREFIX / f"lib/python{minor}/ensurepip/_bundled"
        has_ensurepip = ensurepip is not None or (bundled_wheels.is_dir() and any(bundled_wheels.glob("*.whl")))
        write_maintainer_scripts(root, minor=minor, has_ensurepip=has_ensurepip)
        output = output_dir / f"{package}_{version}_aarch64.deb"
        run("dpkg-deb", "--build", "--root-owner-group", str(root), str(output))

    # Contract checks: no generic command/library aliases may be owned.
    listing = subprocess.check_output(["dpkg-deb", "-c", str(output)], text=True)
    archive_paths: set[str] = set()
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 6:
            path = parts[5]
            if path.startswith("./"):
                path = path[2:]
            archive_paths.add(path)
    for relative in GENERIC_PATHS:
        marker = f"{PREFIX.as_posix()}/{relative}"
        if marker in archive_paths:
            raise RuntimeError(f"Versioned package still owns generic path: {marker}")
    if deb_field(output, "Package") != package:
        raise RuntimeError("Rebuilt package identity mismatch")
    return output, ensure_output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-deb", required=True, type=Path)
    parser.add_argument("--ensurepip-deb", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    py, ensure = repackage_python(args.python_deb, args.output_dir, ensurepip=args.ensurepip_deb)
    print(py)
    if ensure:
        print(ensure)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
