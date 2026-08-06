#!/usr/bin/env python3
"""Patch a workerd source checkout for a native Android/aarch64 Bazel target."""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected patch anchor not found in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tree", type=Path)
    args = parser.parse_args()
    tree = args.tree.resolve()

    module = tree / "MODULE.bazel"
    module_text = module.read_text(encoding="utf-8")
    if "rules_android_ndk" not in module_text:
        anchor = 'module(name = "workerd")\n'
        block = '''module(name = "workerd")

# Community Android/aarch64 target used by termux-python.  The NDK itself is
# supplied by CI through ANDROID_NDK_HOME; Bazel host tools remain native Linux.
bazel_dep(name = "rules_android_ndk", version = "0.1.5")
android_ndk_repository_extension = use_extension(
    "@rules_android_ndk//:extension.bzl",
    "android_ndk_repository_extension",
)
android_ndk_repository_extension.configure(api_level = 24)
use_repo(android_ndk_repository_extension, "androidndk")
register_toolchains("@androidndk//:all")
'''
        replace_once(module, anchor, block)

    build = tree / "BUILD.bazel"
    build_text = build.read_text(encoding="utf-8")
    if 'name = "android_arm64"' not in build_text:
        marker = '# Detect whether we use Linux/macOS/either, used to configure whether tcmalloc/perfetto should be\n# used.\n'
        platform = '''# Native Android/Termux aarch64 target.  This deliberately uses the Android OS
# constraint instead of pretending Bionic is glibc Linux.
platform(
    name = "android_arm64",
    constraint_values = [
        "@platforms//os:android",
        "@platforms//cpu:aarch64",
    ],
)

'''
        replace_once(build, marker, platform + marker)

    build_text = build.read_text(encoding="utf-8")
    if 'name = "is_android"' not in build_text:
        anchor = '''config_setting(
    name = "is_macos",
    constraint_values = ["@platforms//os:macos"],
    visibility = ["//visibility:public"],
)
'''
        replacement = anchor + '''
config_setting(
    name = "is_android",
    constraint_values = ["@platforms//os:android"],
    visibility = ["//visibility:public"],
)
'''
        replace_once(build, anchor, replacement)

    build_text = build.read_text(encoding="utf-8")
    if '        ":is_android",\n' not in build_text:
        replace_once(
            build,
            '''    match_any = [
        ":is_linux",
        ":is_macos",
    ],
''',
            '''    match_any = [
        ":is_linux",
        ":is_macos",
        ":is_android",
    ],
''',
        )

    zlib = tree / "build" / "BUILD.zlib"
    zlib_text = zlib.read_text(encoding="utf-8")
    if 'name = "arm64_android"' not in zlib_text:
        anchor = '''selects.config_setting_group(
    name = "arm64_linux",
    match_all = [
        "@platforms//cpu:aarch64",
        "@platforms//os:linux",
    ],
)
'''
        replacement = anchor + '''
selects.config_setting_group(
    name = "arm64_android",
    match_all = [
        "@platforms//cpu:aarch64",
        "@platforms//os:android",
    ],
)
'''
        replace_once(zlib, anchor, replacement)

    zlib_text = zlib.read_text(encoding="utf-8")
    os_select = '''        "@platforms//os:linux": ["ARMV8_OS_LINUX"],
        "@platforms//os:macos": ["ARMV8_OS_MACOS"],
        "@platforms//os:windows": ["ARMV8_OS_WINDOWS"],
'''
    if '        "@platforms//os:android": ["ARMV8_OS_LINUX"],\n' not in zlib_text:
        replace_once(
            zlib,
            os_select,
            '''        "@platforms//os:linux": ["ARMV8_OS_LINUX"],
        "@platforms//os:android": ["ARMV8_OS_LINUX"],
        "@platforms//os:macos": ["ARMV8_OS_MACOS"],
        "@platforms//os:windows": ["ARMV8_OS_WINDOWS"],
''',
        )

    zlib_text = zlib.read_text(encoding="utf-8")
    if '        ":arm64_android": ["ARMV8_OS_LINUX"],\n' not in zlib_text:
        replace_once(
            zlib,
            '        ":arm64_linux": ["ARMV8_OS_LINUX"],\n',
            '        ":arm64_linux": ["ARMV8_OS_LINUX"],\n        ":arm64_android": ["ARMV8_OS_LINUX"],\n',
        )

    bazelrc = tree / ".bazelrc"
    bazelrc_text = bazelrc.read_text(encoding="utf-8")
    if "build:android --config=unix" not in bazelrc_text:
        bazelrc.write_text(
            bazelrc_text
            + '''
# Community native Android configuration used by termux-python.
# Keep host tools native to the Linux CI runner while target C/C++ uses the NDK.
build:android --config=unix
build:release_android --config=release_unix
build:release_android --@workerd//src/workerd/server:use_tcmalloc=False
build:release_android --@workerd//src/workerd/util:use_perfetto=False
''',
            encoding="utf-8",
        )

    print(f"Patched workerd Android target in {tree}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())